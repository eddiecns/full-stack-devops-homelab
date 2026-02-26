pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    environment {
        DB_NAME = 'bake_db'
        DB_HOST = '127.0.0.1'
        DB_PORT = '3306'

        DB_USER = credentials('db-user')
        DB_PASSWORD = credentials('db-password')

        IMAGE_NAME = 'django-bakery-app'
        DEVOPS_HOST = '192.168.1.182'
    }

    stages {

        stage('Checkout') {
            steps {
                git branch: 'django-app',
                    url: 'git@192.168.1.158:eddie/django-bakery-app.git',
                    credentialsId: 'git-ssh-key'
            }
        }

        stage('Start MySQL') {
            steps {
                sh '''
                    docker run -d --name test-mysql \
                        -e MYSQL_ROOT_PASSWORD=rootpass \
                        -e MYSQL_DATABASE=${DB_NAME} \
                        -e MYSQL_USER=${DB_USER} \
                        -e MYSQL_PASSWORD=${DB_PASSWORD} \
                        -p ${DB_PORT}:3306 \
                        mysql:8.0 --default-authentication-plugin=mysql_native_password

                    echo "Waiting for MySQL to be ready..."
                    until docker exec test-mysql mysqladmin ping -h127.0.0.1 --silent; do
                        sleep 2
                    done

                    echo "Creating user and granting privileges..."
                    docker exec test-mysql mysql -uroot -prootpass -e "
                        CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
                        GRANT ALL PRIVILEGES ON *.* TO '${DB_USER}'@'%' WITH GRANT OPTION;
                        FLUSH PRIVILEGES;"
                '''
            }
        }

        stage('Setup Python') {
            steps {
                sh '''
                    /usr/local/bin/python3.11 -m venv venv
                    . venv/bin/activate
                    python -m pip install --upgrade pip
                    pip install --no-cache-dir -r requirements.txt
                '''
            }
        }

        stage('Migrate Database') {
            steps {
                sh '. venv/bin/activate && python manage.py migrate'
            }
        }

        stage('Run Tests') {
            steps {
                sh '. venv/bin/activate && python manage.py test'
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    def gitCommit = sh(
                        returnStdout: true,
                        script: 'git rev-parse --short HEAD'
                    ).trim()

                    env.IMAGE_TAG = gitCommit
                    def cacheBust = sh(
                        returnStdout: true,
                        script: 'date +%s'
                    ).trim()

                    sh """
                        echo "Building Docker image with tag: ${IMAGE_TAG}..."
                        docker build \
                            --no-cache \
                            --build-arg CACHEBUST=${cacheBust} \
                            -t ${IMAGE_NAME}:${IMAGE_TAG} \
                            -t ${IMAGE_NAME}:latest \
                            .

                        echo "Saving and compressing Docker image..."
                        docker save ${IMAGE_NAME}:${IMAGE_TAG} | gzip > ${IMAGE_NAME}.tar.gz

                        echo "Compressed image size:"
                        du -sh ${IMAGE_NAME}.tar.gz
                    """
                }
            }
        }

        stage('Deploy to Kubernetes (Ansible)') {
            steps {
                sshagent(['devops-ssh-key']) {
                    sh """
                        echo "Copying compressed Docker image to DevOps node..."
                        scp -o StrictHostKeyChecking=no ${IMAGE_NAME}.tar.gz root@${DEVOPS_HOST}:/tmp/

                        echo "Decompressing, updating image tag and deploying..."
                        ssh -o StrictHostKeyChecking=no root@${DEVOPS_HOST} '
                            echo "Decompressing image..."
                            gunzip -f /tmp/${IMAGE_NAME}.tar.gz

                            echo "Updating image tag in deployment.yaml to ${IMAGE_TAG}..."
                            sed -i "s|image: ${IMAGE_NAME}:.*|image: ${IMAGE_NAME}:${IMAGE_TAG}|g" /ecns_projects/myapp/k8s/deployment.yaml

                            echo "Verifying image tag update..."
                            grep "image:" /ecns_projects/myapp/k8s/deployment.yaml

                            cd /ecns_projects/ansible-devops-infra &&
                            ansible-playbook playbooks/deploy_app.yml \
                                -e image_name=${IMAGE_NAME} \
                                -e image_tag=${IMAGE_TAG}
                        '
                    """
                }
            }
        }
    }

    post {
        always {
            sh '''
                docker stop test-mysql 2>/dev/null || true
                docker rm test-mysql 2>/dev/null || true
                rm -f ${IMAGE_NAME}.tar.gz
            '''
        }
        success {
            echo 'Pipeline completed successfully!'
        }
        failure {
            echo 'Pipeline failed. Check the logs above for details.'
        }
    }
}