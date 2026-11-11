"""claude -p 연결·출력 옵션·소요 시간 확인. 실행: python scripts/check_claude_cli.py
결과는 data/logs/claude_cli_check.json 에 저장된다."""
import json, pathlib, shutil, subprocess, time

root = pathlib.Path(__file__).resolve().parents[1]
out_path = root / "data" / "logs" / "claude_cli_check.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
exe = shutil.which("claude") or shutil.which("claude.cmd")
result = {"claude_path": exe}

def run(args, stdin=None, timeout=180):
    t = time.time()
    p = subprocess.run([exe, *args], input=stdin, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return {"args": args, "returncode": p.returncode, "seconds": round(time.time() - t, 1),
            "stdout": p.stdout[-6000:], "stderr": p.stderr[-2000:]}

result["version"] = run(["--version"], timeout=30)
result["help"] = run(["--help"], timeout=30)
prompt = '다음 문장에서 국가와 투자 방식을 JSON으로만 답하세요. 형식: {"country": str, "method": str}\n문장: 회사는 미국 조지아주에 신규 공장을 짓기로 했다.'
result["plain_text"] = run(["-p"], stdin=prompt)
result["output_json"] = run(["-p", "--output-format", "json"], stdin=prompt)
times = []
for _ in range(3):
    r = run(["-p", "--output-format", "json"], stdin=prompt)
    times.append(r["seconds"])
result["repeat_seconds"] = times
out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print("저장:", out_path)
print("버전:", result["version"]["stdout"].strip())
print("텍스트 출력 종료코드:", result["plain_text"]["returncode"], "| JSON 출력 종료코드:", result["output_json"]["returncode"])
print("호출 소요(초):", [result["plain_text"]["seconds"], result["output_json"]["seconds"], *times])
