import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =====================================================================
# KIS API Credentials & Connection Modes
# =====================================================================
KIS_MODE = os.getenv("KIS_MODE", "MOCK").upper() # REAL or MOCK
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "True").lower() == "true"

if KIS_MODE == "REAL":
    KIS_APPKEY = os.getenv("KIS_REAL_APPKEY", "")
    KIS_APPSECRET = os.getenv("KIS_REAL_APPSECRET", "")
    KIS_BASE_URL = "https://openapi.koreainvestment.com:29443"
else:
    KIS_APPKEY = os.getenv("KIS_MOCK_APPKEY", "")
    KIS_APPSECRET = os.getenv("KIS_MOCK_APPSECRET", "")
    KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"

KIS_CANO = os.getenv("KIS_CANO", "")
KIS_ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01")

# =====================================================================
# Strategy C Hyperparameters
# =====================================================================
LONG_TERM_MA_PERIOD = 120    # 120-day MA
FIB_RETRACT_LEVELS = [0.382, 0.5, 0.618] # Fibonacci Levels to watch
PUT_WALL_DISTANCE_LIMIT = 0.03 # 3% distance to Put Wall for "floor" safety
CALL_WALL_DISTANCE_LIMIT = 0.03 # 3% distance to Call Wall for target

# =====================================================================
# Top 50 KOSPI 200 Stock Tickers & Names
# =====================================================================
KOSPI_50_TICKERS = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "005490": "POSCO홀딩스",
    "000270": "기아",
    "068270": "셀트리온",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "035420": "NAVER",
    "000810": "삼성화재",
    "012330": "현대모비스",
    "105560": "KB금융",
    "055550": "신한지주",
    "035720": "카카오",
    "003550": "LG",
    "034730": "SK",
    "017670": "SK텔레콤",
    "015760": "한국전력",
    "009150": "삼성전기",
    "086790": "하나금융지주",
    "032830": "삼성생명",
    "018260": "삼성에스디에스",
    "011200": "HMM",
    "010140": "삼성중공업",
    "329180": "HD현대중공업",
    "003490": "대한항공",
    "034020": "두산에너빌리티",
    "047050": "포스코인터내셔널",
    "096770": "SK이노베이션",
    "251270": "넷마블",
    "028260": "삼성물산",
    "010950": "S-Oil",
    "004020": "현대제철",
    "000100": "유한양행",
    "036570": "엔씨소프트",
    "009540": "HD한국조선해양",
    "011170": "롯데케미칼",
    "024110": "기업은행",
    "008930": "한미사이언스",
    "128940": "한미약품",
    "030200": "KT",
    "078930": "GS",
    "000720": "현대건설",
    "008770": "호텔신라",
    "010060": "OCI홀딩스",
    "001040": "CJ",
    "021240": "코웨이",
    "381220": "TKG휴켐스" # 50개 리스트 완성을 위한 K200 옵션 상장 종목
}
