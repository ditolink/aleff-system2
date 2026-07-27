#!/usr/bin/env python3
"""Inicializa o banco. Execute: python backend/utils/db_init.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from dotenv import load_dotenv
load_dotenv()
from backend.models.database import init_db
init_db()
print("Banco pronto.")
