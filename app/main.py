import os
import time
from flask import Flask, jsonify

app = Flask(__name__)
START_TIME = time.time()

@app.route("/")
def index():
    return jsonify({
        "service": "cloud-native-demo-api",
        "version": os.getenv("APP_VERSION", "v1.0.0"),
        "hostname": os.uname().nodename,
        "status": "running"
    })

@app.route("/healthz")
def healthz():
    """Kubernetes Liveness Probe 存活探针接口"""
    return jsonify({"status": "alive"}), 200

@app.route("/readyz")
def readyz():
    """Kubernetes Readiness Probe 就绪探针接口（模拟启动后3秒就绪）"""
    if time.time() - START_TIME < 3:
        return jsonify({"status": "initializing"}), 503
    return jsonify({"status": "ready"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)