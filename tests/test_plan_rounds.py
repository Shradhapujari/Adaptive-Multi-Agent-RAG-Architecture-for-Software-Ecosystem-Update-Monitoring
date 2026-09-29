"""Manager's per-query round budget: hard questions get an extra round."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from multiagent_rag_v3 import plan_rounds


def test_simple_query_gets_the_default():
    assert plan_rounds("What broke in the latest Proxmox release?", ceiling=2) == 2


def test_comparison_gets_one_extra_round():
    assert plan_rounds("Which is more stable, Teams or Zoom?", ceiling=2) == 3


def test_budget_never_drops_below_the_default():
    assert plan_rounds("chrome update", ceiling=2) == 2


if __name__ == "__main__":
    test_simple_query_gets_the_default()
    test_comparison_gets_one_extra_round()
    test_budget_never_drops_below_the_default()
    print("ok")
