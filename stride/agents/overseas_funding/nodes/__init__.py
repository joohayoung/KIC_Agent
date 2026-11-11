"""노드 1개 = 파일 1개 (5.2의 14개 노드)."""
from agents.overseas_funding.nodes.collect_news import collect_news
from agents.overseas_funding.nodes.extract_news import extract_news
from agents.overseas_funding.nodes.extract_periodic_plan import extract_periodic_plan
from agents.overseas_funding.nodes.collect_disclosures import collect_disclosures
from agents.overseas_funding.nodes.compute_funding_gap import compute_funding_gap
from agents.overseas_funding.nodes.merge_signals import merge_signals
from agents.overseas_funding.nodes.parse_major_events import parse_major_events
from agents.overseas_funding.nodes.parse_request import parse_request
from agents.overseas_funding.nodes.resolve_company import resolve_company
from agents.overseas_funding.nodes.resolve_conflicts import resolve_conflicts
from agents.overseas_funding.nodes.scope_gate import scope_gate
from agents.overseas_funding.nodes.update_state import update_state
from agents.overseas_funding.nodes.write_report import write_report
from agents.overseas_funding.nodes.verify import verify

NODE_FUNCS = {f.__name__: f for f in (parse_request, resolve_company, collect_disclosures, extract_periodic_plan, parse_major_events, collect_news, extract_news, merge_signals, resolve_conflicts, scope_gate, compute_funding_gap, verify, update_state, write_report)}
