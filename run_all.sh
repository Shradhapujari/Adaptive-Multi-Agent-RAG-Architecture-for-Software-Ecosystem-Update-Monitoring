#!/bin/bash
# Run all demo files in order
# Usage: bash run_all.sh

PYTHON="venv311/bin/python3"
W="============================================================"

echo $W
echo "  RUNNING ALL DEMO FILES"
echo $W

echo ""
echo ">>> 1/2  DemoMain3.py — Single Agent Demo"
echo $W
$PYTHON DemoMain3.py demo
echo ""

echo ">>> 2/2  multiagent_rag_v3.py — Multi-Agent RAG System"
echo $W
$PYTHON multiagent_rag_v3.py demo
echo ""

echo $W
echo "  ALL DEMOS COMPLETE"
echo $W
