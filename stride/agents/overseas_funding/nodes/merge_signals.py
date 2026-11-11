import re

from agents.overseas_funding.config import CONFLICT_RATIO, PROJECT_WINDOW_DAYS
from agents.overseas_funding.nodes.parse_major_events import parse_acquisition_form
from agents.overseas_funding.schemas import SignalType
from core.clients import dart
from core.clients.dart_docs import plain_text
from core.nodeguard import guarded

_ws = lambda s: re.sub(r"\s", "", s or "")
AMOUNT_ORDER = (SignalType.FUNDING, SignalType.PLAN, SignalType.PROGRESS)     # S4 다음 순위 (7.8 3)
SOURCE = {SignalType.CONFIRMED: "major_event", SignalType.FUNDING: "major_event", SignalType.PLAN: "periodic", SignalType.PROGRESS: "news"}
CONFLICT_TYPES = (SignalType.CONFIRMED, SignalType.PLAN, SignalType.PROGRESS)     # 조달액은 투자액과 다른 돈이라 비교하지 않는다


def can_merge(rows: list[dict]) -> bool:
    """7.8 합산 조건 (v0.20): 회사명 칸 동일, 이사회결의일 서로 다름, 소유주식수가 누적으로 맞음(앞 공시 취득 후 + 뒤 공시 취득 = 뒤 공시 취득 후).
    누적이 맞으면 한쪽이 다른 쪽의 일부가 아님이 정형 칸으로 확인된다. LLM part_of_earlier는 실행마다 달라 쓰지 않는다."""
    if len(rows) < 2:
        return False
    names = {_ws(x.get("name")) for x in rows}
    boards = [x.get("board") for x in rows]
    if not (len(names) == 1 and "" not in names and None not in boards and len(set(boards)) == len(boards)):
        return False
    ordered = sorted(rows, key=lambda x: x["rcept_dt"])
    return all(None not in (a.get("shares_after"), b.get("shares_acquired"), b.get("shares_after")) and a["shares_after"] + b["shares_acquired"] == b["shares_after"] for a, b in zip(ordered, ordered[1:]))


def rcept_of(signal) -> str | None:
    """S4 본 신호의 원공시 접수번호. 분할된 칸 신호(4칸 id)는 None."""
    parts = signal.signal_id.split(":")
    return parts[2] if signal.signal_type == SignalType.CONFIRMED and len(parts) == 3 else None


def build_projects(signals: list, items: dict) -> tuple[list[dict], dict]:
    """프로젝트 묶기. 회사명 칸이 있는 S4는 회사명으로, 나머지는 국가로 묶는다. LLM `method`는 쓰지 않는다 (v0.20: 실행마다 달라 묶음이 흔들린다).
    반환 (프로젝트, {signal_id: project_key})."""
    projects: dict[str, dict] = {}
    owner: dict[str, str] = {}

    def add(key, s, name=None):
        p = projects.setdefault(key, {"project_key": key, "name": name, "target_country": s.target_country, "signals": [], "items": []})
        p["signals"].append(s)
        owner[s.signal_id] = key
        return p
    ordered = sorted(signals, key=lambda s: s.event_date)
    rest = []
    for s in ordered:      # 회사명 칸이 있는 S4 먼저
        x = items.get(rcept_of(s) or "")
        if x and "form_amount" in x and _ws(x.get("name")):
            gov = ":governance" if s.purpose_category == "governance_restructuring" else ""      # 지배구조 정리는 같은 회사·국가의 성장 투자 금액과 섞지 않는다 (12.2 G-GOV)
            add(f"{s.target_country}:{_ws(x['name'])}{gov}", s, x["name"])["items"].append(x)
        else:
            rest.append(s)

    def open_projects():
        return [p for p in projects.values() if not p["project_key"].endswith(":governance")]

    def near(s):
        """같은 국가, 18개월 이내의 프로젝트. 성장 목적 S4가 있는 것 우선, 그다음 최근 것."""
        cands = [p for p in open_projects() if s.target_country and p["target_country"] == s.target_country and abs((s.event_date - max(x.event_date for x in p["signals"])).days) <= PROJECT_WINDOW_DAYS]
        return max(cands, key=lambda p: (any(x.signal_type == SignalType.CONFIRMED and x.purpose_category == "growth_investment" for x in p["signals"]), max(x.event_date for x in p["signals"])), default=None)
    for s in rest:
        x = items.get(rcept_of(s) or "")
        if s.signal_type == SignalType.FUNDING and not s.target_country:      # 조달 공시에는 국가 칸이 없다. 최근 프로젝트에 붙인다
            p = max(open_projects(), key=lambda p: max(y.event_date for y in p["signals"]), default=None)
        else:
            p = near(s)
        key = p["project_key"] if p else f"{s.target_country or '미상'}:{s.signal_type.value[:2]}"
        p = add(key, s, x.get("name") if x else None)
        if x:
            p["items"].append(x)
    return list(projects.values()), owner


def finish_project(p: dict) -> dict:
    """대표 금액과 단계 (7.8 3~4). 금액 항목은 지배회사 출자 우선, 종속회사 집행은 지배회사 출자가 없을 때만."""
    sig, items = p.pop("signals"), p.pop("items")
    parents = [x for x in items if not x.get("execution")]
    rows = parents or items
    merged = can_merge(rows)
    s4 = [s for s in sig if s.signal_type == SignalType.CONFIRMED]
    purposes = [s.purpose_category for s in (s4 or sig)]
    purpose = "growth_investment" if "growth_investment" in purposes else next((x for x in purposes if x != "unknown"), "unknown")
    amount, source, amount_ids = None, "missing", []
    if rows:
        latest = max(rows, key=lambda x: x["rcept_dt"])
        amount, source = (sum(x["amount"] or 0 for x in rows) if merged else latest["amount"]), "major_event"
        nos = {x["rcept_no"] for x in rows}
        amount_ids = [s.signal_id for s in s4 if rcept_of(s) in nos]
    else:
        for t in AMOUNT_ORDER:
            found = sorted((s for s in sig if s.signal_type == t and s.amount_krw is not None), key=lambda s: s.event_date)
            if found:
                amount = sum(s.amount_krw for s in found) if t == SignalType.FUNDING else found[-1].amount_krw
                source, amount_ids = SOURCE[t], [s.signal_id for s in found]
                break
    latest_date = max(s.event_date for s in sig)
    return {**p, "method": next((s.method for s in reversed(s4 or sig) if s.method), None), "purpose_category": purpose, "is_overseas": True, "stage": max(int(s.stage) for s in (s4 or sig)), "change_direction": "none", "amount_krw": amount, "amount_source": source,
            "signal_ids": [s.signal_id for s in sig], "amount_signal_ids": amount_ids, "rcept_nos": [x["rcept_no"] for x in rows], "execution_rcept_nos": [x["rcept_no"] for x in items if x.get("execution") and parents], "corrections": [c for x in items for c in x.get("corrections") or []], "mergeable": merged,
            "latest_s4_date": max((s.event_date for s in s4), default=None), "latest_event_date": latest_date, "has_new_signal": any((s.signal_type == SignalType.PLAN and s.is_new is True) or s.signal_type != SignalType.PLAN for s in sig)}


def link_s6(no: str, text: str, projects: list[dict]) -> dict | None:
    """S6 정형 연결 (7.9, v0.20): 원공시의 정정 접수번호이거나, 회사명 칸이 프로젝트 회사명과 같을 때만. 문장에 이름이 나오는 것만으로는 연결하지 않는다."""
    for p in projects:
        if no in p["corrections"]:
            return p
    squashed = _ws(text)
    for p in projects:
        name = _ws(p.get("name"))
        if name and re.search(r"(?:출자회사명|회사명\(국적\)|회사명):?" + re.escape(name), squashed):
            return p
    return None


def structured_direction(f, text: str, original_text: str | None) -> str | None:
    """정형 칸·공시 이름에서 변경 방향을 읽는다. 읽을 수 없으면 None이고 그때만 LLM 라벨을 쓴다 (v0.20)."""
    m = re.search(r"정정사유\s*(.{0,80})", text[:800])
    reason = m.group(1) if m else ""
    if re.search(r"취득\s*완료|납입\s*완료", reason):
        return "none"
    if re.search(r"철회|취소|해제|해지", f.report_nm_norm + " " + reason):
        return "cancelled"
    if original_text is not None:
        old, new = parse_acquisition_form(original_text), parse_acquisition_form(text)
        if old["amount"] and new["amount"] and old["amount"] != new["amount"]:
            return "reduced" if new["amount"] < old["amount"] else "expanded"
        if old["scheduled"] and new["scheduled"]:
            return "postponed" if new["scheduled"] > old["scheduled"] else "none"
        return "none"
    if "연기" in f.report_nm_norm + reason:
        return "postponed"
    if "축소" in f.report_nm_norm + reason:
        return "reduced"
    return None


def apply_s6(signals: list, projects: list[dict], filings: list, corr_owner: dict) -> tuple[list, list[dict]]:
    """연결된 S6만 프로젝트 단계·방향에 반영하고, 연결되지 않은 S6는 기록만 남긴다. 반환 (남길 S6, 연결 안 된 S6 기록)."""
    by_no = {f.rcept_no: f for f in filings}
    client, kept, unlinked = None, [], []
    for s in sorted(signals, key=lambda s: s.event_date):
        no = s.signal_id.split(":")[2]
        client = client or dart.get_client()
        text = plain_text(client.document(no))
        p = link_s6(no, text, projects)
        if p is None:
            if s.change_direction != "none":
                unlinked.append({"signal_id": s.signal_id, "event_date": s.event_date.isoformat(), "llm_change_direction": s.change_direction, "evidence_ids": s.evidence_ids})
            continue
        original = plain_text(client.document(corr_owner[no])) if no in corr_owner else None
        direction = structured_direction(by_no[no], text, original) or s.change_direction or "none"
        if direction == "none":
            continue
        kept.append(s.model_copy(update={"change_direction": direction, "project_key": p["project_key"], "summary": f"{direction}: {by_no[no].report_nm_norm}"[:200]}))
        latest_s4 = p.get("latest_s4_date")
        if latest_s4 and s.event_date < latest_s4:      # 뒤에 새 결정이 있으면 지난 변경은 현재 단계를 바꾸지 않는다 (v0.20)
            continue
        if direction == "cancelled":
            p.update(stage=1, change_direction="cancelled")
        elif direction in ("postponed", "reduced"):
            p.update(stage=max(1, p["stage"] - 1), change_direction=direction)
        elif p["change_direction"] == "none":
            p["change_direction"] = direction
        p["signal_ids"].append(s.signal_id)
    return kept, unlinked


def find_conflicts(projects: list[dict], signals: dict, resolved: dict) -> list[dict]:
    """같은 프로젝트에서 출처별 금액이 20% 넘게 다르면 기록한다 (7.8 5). 이미 처리한 충돌은 그대로 둔다."""
    out = list(resolved.values())
    for p in projects:
        rows = [signals[i] for i in p["signal_ids"] if i in signals and signals[i].signal_type in CONFLICT_TYPES and signals[i].amount_krw]
        amounts = [s.amount_krw for s in rows]
        if len({s.signal_type for s in rows}) < 2 or (max(amounts) - min(amounts)) / max(amounts) <= CONFLICT_RATIO:
            continue
        key = p["project_key"]
        if key not in resolved:
            out.append({"project_key": key, "signal_ids": [s.signal_id for s in rows], "amounts": amounts, "sources": [s.signal_type.value for s in rows], "resolved": False})
    return out


@guarded
def merge_signals(state) -> dict:
    """여러 출처의 신호를 프로젝트로 묶고 대표 금액·단계를 정한다 (7.8). LLM 없음. 이후 노드는 signals_merged와 projects만 읽는다."""
    last = {s.signal_id: s for s in state.get("signals") or []}      # ponytail: 재추출로 사건 수가 줄면 옛 S2가 남는다. 7.7 사건 id를 내용 기준으로 바꾸면 해결된다
    signals = list(last.values())
    items = {x["rcept_no"]: x for x in state.get("s4_items") or []}
    s6 = [s for s in signals if s.signal_type == SignalType.ALERT]
    main = [s for s in signals if s.signal_type != SignalType.ALERT and s.is_overseas is True and (s.signal_type != SignalType.CONFIRMED or rcept_of(s) in items) and not (s.signal_type == SignalType.FUNDING and s.amount_krw is None)]
    raw, _ = build_projects(main, items)
    corr_owner = {c: x["rcept_no"] for x in items.values() for c in x.get("corrections") or []}      # 정정 접수번호 → 원공시 접수번호
    projects = [finish_project(p) for p in raw]
    kept_s6, unlinked = apply_s6(s6, projects, state.get("filings") or [], corr_owner)
    for p in projects:
        p["latest_event_date"] = p["latest_event_date"].isoformat()
        p["latest_s4_date"] = p["latest_s4_date"].isoformat() if p["latest_s4_date"] else None
    owner = {i: p["project_key"] for p in projects for i in p["signal_ids"]}
    merged = [s.model_copy(update={"project_key": owner.get(s.signal_id)}) for s in signals if s.signal_type != SignalType.ALERT] + kept_s6
    resolved = {c["project_key"]: c for c in state.get("conflicts") or [] if c.get("resolved")}
    conflicts = find_conflicts(projects, {s.signal_id: s for s in merged}, resolved)
    return {"signals_merged": merged, "projects": projects, "unlinked_s6": unlinked, "conflicts": conflicts}

