# EC2 / Linux Server Deployment Runbook

목표: PC를 꺼도 `scheduler.py`가 서버에서 계속 실행되고 Telegram 알림을 보내게 한다.

## 1. 서버 접속

```bash
ssh -i your-key.pem ubuntu@YOUR_SERVER_IP
```

## 2. 설치

```bash
sudo apt-get update
sudo apt-get install -y git python3.11 python3.11-venv
cd /opt
sudo git clone https://github.com/shopper12/stock_scanner.git stock_scanner
sudo chown -R $USER:$USER /opt/stock_scanner
cd /opt/stock_scanner
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3. 즉시 실행 테스트

```bash
python scan_once.py --notify
```

Telegram 메시지가 오면 정상이다.

## 4. systemd 등록

```bash
sudo cp deploy/systemd_stock_scanner.service /etc/systemd/system/stock_scanner.service
sudo systemctl daemon-reload
sudo systemctl enable stock_scanner
sudo systemctl start stock_scanner
sudo systemctl status stock_scanner
```

## 5. 로그 확인

```bash
sudo journalctl -u stock_scanner -f
```

## 6. 코드 업데이트

```bash
cd /opt/stock_scanner
sudo systemctl stop stock_scanner
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl start stock_scanner
sudo systemctl status stock_scanner
```

## 7. 수동 재실행

```bash
sudo systemctl restart stock_scanner
```

## 8. 중지

```bash
sudo systemctl stop stock_scanner
sudo systemctl disable stock_scanner
```

## 주의

현재 `.env`가 repo에 커밋되어 있으므로 서버에서 별도 `.env` 작성 없이 바로 동작한다. 여러 컴퓨터에서 동일 설정을 쓰려는 목적에는 편하지만, 저장소 접근권한 관리는 사용자가 직접 책임져야 한다.
