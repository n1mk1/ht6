# RehabTrace dev loop. Edit locally -> `make deploy` -> use the dashboard.

.PHONY: help sync build server dash stop-server imu-cal shell info deploy

help:
	@echo "  make deploy    - sync + build rt_vision + (re)start server"
	@echo "  make sync      - rsync this folder to the Pi"
	@echo "  make build     - compile rt_vision on the Pi"
	@echo "  make server    - (re)start the control server on the Pi"
	@echo "  make dash      - open the dashboard in your browser"
	@echo "  make imu-cal   - quick IMU bias calibration test"
	@echo "  make shell     - interactive SSH into the project dir"

sync:
	@./scripts/sync.sh

build: sync
	@./scripts/pi.sh 'cd ~/steadyeye/vision && g++ -O2 -std=c++17 -o rt_vision rt_vision.cpp -lcamapi -lscreen && echo BUILD_OK'

server: sync
	@./scripts/pi.sh 'pidin ar 2>/dev/null | grep "server/server.py" | grep -v grep | awk "{print \$$1}" | xargs -r kill 2>/dev/null; sleep 2; cd ~/steadyeye && (nohup ~/venv/bin/python server/server.py > server.log 2>&1 &) && sleep 2 && head -2 server.log'

deploy: build server
	@echo "dashboard: http://qnxpi23.local:8080/"

dash:
	@open http://qnxpi23.local:8080/

stop-server:
	@./scripts/pi.sh 'kill $$(cat ~/steadyeye/server.pid 2>/dev/null) 2>/dev/null && echo stopped || echo "not running"'

imu-cal: sync
	@./scripts/pi.sh '~/venv/bin/python ~/steadyeye/imu/imu_recorder.py calibrate --out /tmp/bias.json --seconds 2'

shell:
	@bash -c 'source ./env.sh; ssh -tt $$SSH_OPTS $$PI_USER@$$PI_HOST "cd $$PI_DIR; exec bash"'

info:
	@./scripts/pi.sh 'uname -a; ls /dev/sensor/ /dev/i2c1; ls /usr/include/camera/camera_api.h 2>&1'
