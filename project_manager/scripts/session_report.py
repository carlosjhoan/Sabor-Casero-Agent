#!/usr/bin/env python
# context_manager/scripts/session_report.py

"""
Genera reporte de progreso de la sesión.
Uso: python session_report.py
"""

import yaml
from pathlib import Path
from datetime import datetime

def load_goals():
    guidelines_path = Path(__file__).parent.parent / "guidelines" / "session_goals.yaml"
    with open(guidelines_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def generate_report():
    data = load_goals()
    
    from datetime import date
    today = date.today().isoformat()
    
    report = []
    report.append(f"# 📊 Reporte de Sesión - {today}\n")
    
    for session in data["sessions"]:
        if session.get("date") == today or session.get("status") == "in_progress":
            report.append(f"## 🎯 Objetivo: {session['objective']}")
            report.append(f"**Prioridad:** {session['priority']}")
            report.append(f"**Estado:** {session['status']}\n")
            
            # Estadísticas de tareas
            tasks = session["tasks"]
            total = len(tasks)
            completed = len([t for t in tasks if t["status"] == "completed"])
            pending = total - completed
            
            report.append(f"### 📈 Progreso")
            report.append(f"- Total tareas: {total}")
            report.append(f"- Completadas: {completed}")
            report.append(f"- Pendientes: {pending}")
            report.append(f"- Progreso: {completed/total*100:.1f}%\n")
            
            if pending > 0:
                report.append("### ⏳ Tareas Pendientes")
                for task in tasks:
                    if task["status"] != "completed":
                        report.append(f"- {task['description']}")
            
            if session.get("notes"):
                report.append("\n### 📝 Notas de la sesión")
                for note in session["notes"]:
                    report.append(f"- {note}")
    
    # Guardar reporte
    report_path = Path(__file__).parent.parent / "session_notes.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report))
    
    print("\n".join(report))
    print(f"\n✅ Reporte guardado en {report_path}")

if __name__ == "__main__":
    generate_report()