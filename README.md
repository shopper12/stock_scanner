# Stock Scanner

미국 장기 ETF, 한국 퇴직연금 ETF, 한국 단기 일반계좌 후보, USD/KRW 환전 판단을 분리한 Python 스캐너입니다.

## 핵심 구조

- `US_LONG_ETF`: 미국 단기 주식 매매 없음. 장기 ETF만 점수화하고 분할매수 비중을 계산합니다.
- `KR_RETIREMENT_ETF`: 한국 장기투자는 퇴직연금 계좌에서 매수 가능한 ETF만 대상으로 합니다. 개별주 추천을 하지 않습니다.
- `KR_SHORT_STOCK`: 한국 단기 매매는 일반계좌 전용입니다.
- `FX_CONVERSION`: USD/KRW, 20/60/120일 평균, DXY, 미국 10년물, VIX를 이용해 선환전/분할환전/최소환전을 판단합니다.
- `notifier.py`: 텔레그램으로 모바일 알림을 보냅니다.
- `scheduler.py`: PC가 아니라 EC2 같은 서버에서 계속 실행하는 용도입니다.

## 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python scan_once.py
```

텔레그램 알림까지 테스트:

```powershell
python scan_once.py --notify
```

대시보드:

```powershell
streamlit run dashboard/streamlit_app.py
```

## 모바일로 쓰는 권장 방식

로컬 PC에서 실행하면 PC를 켜둬야 합니다. 모바일 업무 중 사용하려면 아래 구조가 맞습니다.

```text
AWS EC2 / Oracle VM / Lightsail
  ↓
scheduler.py 상시 실행
  ↓
Telegram Bot 알림
  ↓
Streamlit 모바일 대시보드
```

## EC2 배포 개요

```bash
sudo bash deploy/ec2_setup.sh
cd /opt/stock_scanner
nano .env
sudo cp deploy/systemd_stock_scanner.service /etc/systemd/system/stock_scanner.service
sudo systemctl daemon-reload
sudo systemctl enable stock_scanner
sudo systemctl start stock_scanner
sudo systemctl status stock_scanner
```

## .env 주요 항목

```env
USE_MOCK_DATA=1
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ACCOUNT_EQUITY_KRW=10000000
RETIREMENT_TOTAL_KRW=10000000
US_MONTHLY_BUDGET_KRW=1000000
```

처음에는 `USE_MOCK_DATA=1`로 실행 검증 후, 실제 데이터 연동 시 `0`으로 바꿉니다.

## 주의

이 프로그램은 수익을 보장하지 않습니다. 백테스트/스캐너/알림 도구이며, 실제 주문은 별도 검증 후 붙여야 합니다. 특히 퇴직연금 ETF는 증권사별 매수 가능 상품이 달라 CSV 또는 API로 반드시 대조해야 합니다.
