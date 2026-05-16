# Stock Scanner Android App

개인 사용용 Android 단독 실행 MVP입니다.

## 현재 버전 범위

- 서버 없이 앱 안에서 mock 기반 스캐너 실행
- 수동 스캔 버튼
- 텔레그램 전송 버튼
- WorkManager 15분 반복 자동 실행
- 미국 장기 ETF / 환율 / 퇴직연금 / 한국 단기 후보 화면 표시

## 아직 아닌 것

- Python 스캐너의 모든 실데이터 로직 완전 이식은 아직 아님
- KIS/pykrx/yfinance 실시간 데이터 직접 연동은 다음 단계
- 특정 시각 정밀 알림은 아직 WorkManager 15분 반복 기반

## 실행

Android Studio에서 `android_app` 폴더를 열고 Gradle Sync 후 실행한다.

```powershell
cd C:\codetest\stock_scanner
git pull
```

Android Studio:

```text
File > Open > C:\codetest\stock_scanner\android_app
Run app
```

## 휴대폰에서 백그라운드 제한 예외

설치 후 다음을 직접 설정한다.

```text
설정 > 앱 > Stock Scanner > 배터리 > 제한 없음
설정 > 앱 > Stock Scanner > 알림 허용
```

제조사별 절전/자동시작 제한도 해제해야 한다.

## 다음 단계

1. Android 빌드 오류 수정
2. APK 설치 확인
3. 텔레그램 전송 버튼 테스트
4. WorkManager 자동 실행 테스트
5. Python 쪽 스캐너 로직을 Kotlin으로 단계적 이식
6. 실데이터 API 연결
