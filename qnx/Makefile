# Praxis QNX dev loop. Edit locally -> `make deploy` -> use the dashboard.

.PHONY: help sync build server dash dataset pull-dataset ai-train ai-install ai-models ai stop-server imu-cal shell info deploy

help:
	@echo "  make deploy    - sync + build rt_vision + (re)start server"
	@echo "  make sync      - rsync this folder to the Pi"
	@echo "  make build     - compile rt_vision on the Pi"
	@echo "  make server    - (re)start the control server on the Pi"
	@echo "  make dash      - open the dashboard in your browser"
	@echo "  make dataset   - open the image-quality capture UI"
	@echo "  make pull-dataset - copy captured images from the Pi into this repo"
	@echo "  make ai-train  - train the image-quality model from captured data"
	@echo "  make ai-install - install official QNX llama.cpp packages app-locally"
	@echo "  make ai-models - verify and copy GGUF model files to the Pi"
	@echo "  make ai        - train, install, copy models, and deploy"
	@echo "  make imu-cal   - quick IMU bias calibration test"
	@echo "  make shell     - interactive SSH into the project dir"

sync:
	@./scripts/sync.sh

build: sync
	@./scripts/pi.sh 'cd ~/steadyeye/vision && g++ -O2 -std=c++17 -o rt_vision rt_vision.cpp -lcamapi -lscreen && echo BUILD_OK'

server: sync
	@./scripts/pi.sh 'pidin ar 2>/dev/null | grep "server/server.py" | grep -v grep | awk "{print \$$1}" | xargs -r kill 2>/dev/null; sleep 2; cd ~/steadyeye; set -a; [ ! -f device.env ] || . ./device.env; set +a; (nohup ~/venv/bin/python server/server.py > server.log 2>&1 &) && sleep 2 && head -2 server.log'

deploy: build server
	@echo "dashboard: http://qnxpi23.local:8080/"

dash:
	@open http://qnxpi23.local:8080/

dataset:
	@open http://qnxpi23.local:8080/dataset

pull-dataset:
	@./scripts/pull-image-dataset.sh

ai-train:
	@python3 image_quality/train.py

ai-install: sync
	@./scripts/pi.sh 'bash ~/steadyeye/scripts/install-llama-local.sh'

ai-models:
	@./scripts/push-ai-models.sh

ai: ai-train ai-install ai-models deploy

stop-server:
	@./scripts/pi.sh 'kill $$(cat ~/steadyeye/server.pid 2>/dev/null) 2>/dev/null && echo stopped || echo "not running"'

imu-cal: sync
	@./scripts/pi.sh '~/venv/bin/python ~/steadyeye/imu/imu_recorder.py calibrate --out /tmp/bias.json --seconds 2'

shell:
	@bash -c 'source ./env.sh; ssh -tt $$SSH_OPTS $$PI_USER@$$PI_HOST "cd $$PI_DIR; exec bash"'

info:
	@./scripts/pi.sh 'uname -a; ls /dev/sensor/ /dev/i2c1; ls /usr/include/camera/camera_api.h 2>&1'
