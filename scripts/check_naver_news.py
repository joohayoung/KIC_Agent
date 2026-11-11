"""네이버 뉴스 검색 API 연결 확인. 실행: python scripts/check_naver_news.py"""
import json, pathlib, urllib.parse, urllib.request

env = {}
for line in pathlib.Path(__file__).resolve().parents[1].joinpath(".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

provider = env.get("NAVER_NEWS_PROVIDER", "ncp_api_hub")
params = {"query": "해외 공장 증설", "display": 3, "start": 1, "sort": "date"}
if provider == "ncp_api_hub":
    url = env.get("NAVER_NEWS_URL", "https://naverapihub.apigw.ntruss.com/search/v1/news")
    headers = {"X-NCP-APIGW-API-KEY-ID": env["NAVER_CLIENT_ID"], "X-NCP-APIGW-API-KEY": env["NAVER_CLIENT_SECRET"]}
else:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {"X-Naver-Client-Id": env["NAVER_CLIENT_ID"], "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"]}

req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers=headers)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    print("성공 · 전체 결과 수:", data.get("total"))
    for it in data.get("items", []):
        print("-", it.get("pubDate"), "|", it.get("title"))
except urllib.error.HTTPError as e:
    print("실패 HTTP", e.code, e.read().decode("utf-8", "ignore")[:300])
