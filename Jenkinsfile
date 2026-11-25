pipeline {
    agent any

    environment {
        REGISTRY = "registry.local/prod"
        IMAGE_NAME = "demo-web-app"
        IMAGE_TAG = "${env.BUILD_NUMBER}-${sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()}"
        K8S_NAMESPACE = "prod-cicd"
    }

    stages {
        stage('Checkout Code') {
            steps {
                checkout scm
                echo "Checked out commit: ${IMAGE_TAG}"
            }
        }

        stage('Docker Multi-Stage Build') {
            steps {
                sh """
                    docker build -f docker/Dockerfile -t ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG} ${REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }

        stage('Push to Private Registry') {
            steps {
                sh """
                    docker push ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}
                    docker push ${REGISTRY}/${IMAGE_NAME}:latest
                """
            }
        }

        stage('Deploy to Kubernetes') {
            steps {
                sh """
                    kubectl apply -f k8s/namespace.yaml
                    kubectl apply -f k8s/service.yaml
                    sed -i "s|image: .*|image: ${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}|g" k8s/deployment.yaml
                    kubectl apply -f k8s/deployment.yaml
                    kubectl rollout status deployment/demo-web-app -n ${K8S_NAMESPACE} --timeout=120s
                """
            }
        }
    }

    post {
        success {
            echo "Deployment succeeded! Version: ${IMAGE_TAG}"
        }
        failure {
            echo "Deployment failed! Triggering rollback check..."
            sh "kubectl rollout undo deployment/demo-web-app -n ${K8S_NAMESPACE} || true"
        }
    }
}