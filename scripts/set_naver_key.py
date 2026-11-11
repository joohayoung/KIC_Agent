"""네이버 API 키를 .env에 저장한다. 실행: python scripts/set_naver_key.py
콘솔의 복사 버튼으로 복사한 값을 그대로 붙여 넣는다 (Secret은 화면에 표시되지 않음)."""
import getpass, pathlib, subprocess, sys

env_path = pathlib.Path(__file__).resolve().parents[1] / ".env"
cid = input("Client ID 붙여넣기: ").strip()
secret = getpass.getpass("Client Secret 붙여넣기 (입력해도 화면에 안 보임): ").strip()
lines = env_path.read_text(encoding="utf-8").splitlines()
out, seen = [], set()
for line in lines:
    key = line.split("=", 1)[0]
    if key == "NAVER_CLIENT_ID":
        line = f"NAVER_CLIENT_ID={cid}"
    elif key == "NAVER_CLIENT_SECRET":
        line = f"NAVER_CLIENT_SECRET={secret}"
    seen.add(key)
    out.append(line)
if "NAVER_CLIENT_ID" not in seen:
    out.append(f"NAVER_CLIENT_ID={cid}")
if "NAVER_CLIENT_SECRET" not in seen:
    out.append(f"NAVER_CLIENT_SECRET={secret}")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"저장 완료 (ID {len(cid)}자, Secret {len(secret)}자). 연결 확인을 시작합니다.")
subprocess.run([sys.executable, str(pathlib.Path(__file__).with_name("check_naver_news.py"))])
