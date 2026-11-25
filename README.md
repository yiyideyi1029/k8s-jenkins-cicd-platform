# 基于 Jenkins 与 Kubernetes 的业务系统 CI/CD 自动化部署平台

## 一、项目背景

在传统部署模式下，业务系统上线依赖人工登录服务器执行 `git pull`、`pip install`、重启进程等操作，
存在**发布流程不可追溯、环境不一致、回滚耗时长、发布期间服务中断**等典型问题。

本项目以 Python Flask 微服务为示例业务系统，构建一条从**代码提交**到**生产环境滚动发布**的
全自动 CI/CD 流水线：Jenkins 通过 Webhook 感知代码变更，基于多阶段构建产出精简镜像并推送至
私有镜像仓库（Harbor / Registry），最终由 Kubernetes 以零中断的滚动更新策略完成灰度替换，
配合存活/就绪双探针与失败自动回滚机制，将一次发布的人工干预成本降至零。

## 二、架构设计

```text
┌──────────┐   git push    ┌──────────────┐   Webhook    ┌─────────────────────┐
│ Developer │ ────────────▶ │  Git Server  │ ───────────▶ │       Jenkins       │
└──────────┘               └──────────────┘              │  (Declarative       │
                                                          │   Pipeline)         │
                                                          └──────────┬──────────┘
                                                                     │  ① docker build
                                                                     │     (multi-stage)
                                                                     ▼
                                                          ┌─────────────────────┐
                                                          │  Docker Multi-Stage │
                                                          │  Builder → Runtime  │
                                                          └──────────┬──────────┘
                                                                     │  ② docker push
                                                                     ▼
                                                          ┌─────────────────────┐
                                                          │  Harbor / Registry  │
                                                          │  :BUILD_NUMBER-SHA  │
                                                          └──────────┬──────────┘
                                                                     │  ③ kubectl apply
                                                                     │     + rollout status
                                                                     ▼
                    ┌──────────────────────────────────────────────────────────────┐
                    │                    Kubernetes  prod-cicd                     │
                    │  ┌────────────────────────────────────────────────────────┐  │
                    │  │ Deployment: demo-web-app  (replicas=3)                 │  │
                    │  │  RollingUpdate: maxSurge=1 / maxUnavailable=0          │  │
                    │  │  ┌─────────┐   ┌─────────┐   ┌─────────┐               │  │
                    │  │  │ Pod v1  │──▶│ Pod v2  │──▶│ Pod v2  │  ...          │  │
                    │  │  └─────────┘   └─────────┘   └─────────┘               │  │
                    │  │  livenessProbe: /healthz   readinessProbe: /readyz     │  │
                    │  └────────────────────────────────────────────────────────┘  │
                    │  ┌────────────────────────────────────────────────────────┐  │
                    │  │ Service: demo-web-service (NodePort 30080)             │  │
                    │  └────────────────────────────────────────────────────────┘  │
                    └──────────────────────────────────────────────────────────────┘
```

**流水线阶段（`Jenkinsfile`）**

| 阶段 | 动作 | 产出 |
| --- | --- | --- |
| Checkout Code | `checkout scm`，取短 SHA 拼接镜像标签 | 唯一版本号 `BUILD_NUMBER-SHA` |
| Docker Multi-Stage Build | `docker build -f docker/Dockerfile` | 瘦身运行镜像 + `latest` 别名 |
| Push to Private Registry | 推送版本标签与 `latest` | 仓库中可回溯的镜像制品 |
| Deploy to Kubernetes | `kubectl apply` + `rollout status --timeout=120s` | 滚动发布完成或失败中断 |

## 三、核心技术亮点

### 1. 多阶段构建镜像瘦身

`docker/Dockerfile` 采用 **Builder + Runtime 两阶段**结构：

- `builder` 阶段基于 `python:3.11-slim`，仅负责 `pip install --prefix=/install` 完成依赖编译；
- `runtime` 阶段基于 `python:3.11-alpine`，**只拷贝 `/install` 下的已安装依赖与业务代码**，
  编译工具链、pip 缓存、源码包全部留在上一阶段并被丢弃；
- 指令层面追加 `--no-cache-dir`，并以非 root 用户 `appuser(1001)` 运行，兼顾体积与安全基线。

| 构建方式 | 基础镜像 | 镜像体积 | 单节点首次拉取耗时（参考） |
| --- | --- | --- | --- |
| 单阶段构建 | `python:3.11` | 约 **1.01 GB** | 约 90 ~ 120 s |
| 多阶段构建（本项目） | `python:3.11-alpine` | 约 **65 MB** | 约 5 ~ 10 s |

> 镜像体积由约 **1.01 GB 降至约 65 MB，缩减约 93%**，属于 60% 以上的量级优化。
> 直接收益是：节点磁盘占用下降、镜像仓库存储与带宽成本下降、
> **Pod 冷启动与滚动发布期间新副本的调度速度显著提升**，扩容与故障重建更快。

### 2. 零中断滚动发布

- `strategy.rollingUpdate.maxUnavailable: 0` + `maxSurge: 1`：
  发布过程中**始终保证可用副本数不低于期望值**，先起新 Pod、就绪后再摘除旧 Pod。
- `readinessProbe` 指向 `/readyz`：该接口在进程启动后 3 秒内返回 `503`，
  确保**只有真正具备服务能力的 Pod 才会被加入 Service Endpoints**，避免流量打到半启动实例。
- `livenessProbe` 指向 `/healthz`：进程僵死时由 kubelet 自动重启容器，实现故障自愈。
- `revisionHistoryLimit: 5` 保留历史版本，配合 Jenkins `post.failure` 中的
  `kubectl rollout undo` 实现**发布失败自动回滚**。
- 资源 `requests/limits`（100m/128Mi ~ 500m/256Mi）为调度与 HPA 提供依据，防止资源争抢导致抖动。

### 3. 版本可追溯

镜像标签使用 `BUILD_NUMBER-<short SHA>` 双因子，任何一次线上故障都能精确映射到
Jenkins 构建号与 Git 提交，满足审计与快速回滚诉求。

## 四、目录结构

```text
k8s-jenkins-cicd-platform/
├── app/
│   ├── main.py                  # Flask 微服务（含 /healthz、/readyz 探针接口）
│   └── requirements.txt         # 依赖清单
├── docker/
│   ├── Dockerfile               # 多阶段构建（镜像瘦身核心）
│   └── nginx.conf               # Nginx 反向代理配置
├── k8s/
│   ├── namespace.yaml           # 独立命名空间 prod-cicd
│   ├── deployment.yaml          # 滚动更新策略 + 双探针
│   └── service.yaml             # NodePort 30080 暴露
├── Jenkinsfile                  # 声明式 CI/CD 流水线
└── README.md
```

## 五、本地快速部署

### 1. 本地运行服务（不使用容器）

```bash
pip install -r app/requirements.txt
python app/main.py
# 访问 http://127.0.0.1:8000/  /healthz  /readyz
```

### 2. 构建镜像并本地验证

```bash
docker build -f docker/Dockerfile -t demo-web-app:v1.0.0 .
docker images demo-web-app:v1.0.0
docker run -d -p 8000:8000 --name demo-web-app demo-web-app:v1.0.0
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

### 3. 部署到 Kubernetes

```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/deployment.yaml

kubectl rollout status deployment/demo-web-app -n prod-cicd --timeout=120s
kubectl get pods -n prod-cicd -o wide
kubectl get svc -n prod-cicd
# 浏览器访问 http://<任意节点IP>:30080/
```

### 4. 验证零中断与回滚能力

```bash
# 滚动发布观察（可另开窗口持续 curl 验证无 5xx）
kubectl set image deployment/demo-web-app web-container=registry.local/prod/demo-web-app:v1.0.1 -n prod-cicd
kubectl rollout status deployment/demo-web-app -n prod-cicd

# 手动回滚
kubectl rollout undo deployment/demo-web-app -n prod-cicd
kubectl rollout history deployment/demo-web-app -n prod-cicd
```

### 5. Jenkins 侧接入

1. Jenkins 安装 `Docker Pipeline`、`Kubernetes CLI`、`Git` 插件；
2. 新建 Pipeline 任务，SCM 指向本仓库，脚本路径 `Jenkinsfile`；
3. 在 Git 服务端配置 Webhook 指向 `http://<jenkins>/generic-webhook-trigger/invoke`；
4. 在 Jenkins 凭据中配置镜像仓库登录信息，执行 `docker login registry.local` 后即可触发流水线。

## 六、环境要求

| 组件 | 版本要求 |
| --- | --- |
| Python | 3.11+ |
| Docker | 20.10+（支持多阶段构建） |
| Kubernetes | 1.24+ |
| Jenkins | 2.400+（声明式 Pipeline） |
| kubectl | 与集群版本一致 |