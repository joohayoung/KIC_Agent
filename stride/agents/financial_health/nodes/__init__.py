"""노드 1개 = 파일 1개, 파일명 = 노드명 (공통 양식 5장)."""
from agents.financial_health.nodes.collect_audit_info import collect_audit_info
from agents.financial_health.nodes.collect_financials import collect_financials
from agents.financial_health.nodes.collect_market_data import collect_market_data
from agents.financial_health.nodes.collect_restructuring import collect_restructuring
from agents.financial_health.nodes.compute_metrics import compute_metrics
from agents.financial_health.nodes.parse_request import parse_request
from agents.financial_health.nodes.resolve_company import resolve_company
from agents.financial_health.nodes.update_state import update_state
from agents.financial_health.nodes.verify import verify
from agents.financial_health.nodes.write_report import write_report

NODES = {f.__name__: f for f in (parse_request, resolve_company, collect_financials, collect_audit_info, collect_restructuring, collect_market_data, compute_metrics, verify, update_state, write_report)}
