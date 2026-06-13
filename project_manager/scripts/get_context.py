#!/usr/bin/env python
# context_manager/scripts/get_context.py

"""
Obtiene el contexto de la sesión actual para usar en OpenCode.
Uso: python get_context.py
"""

import yaml
from pathlib import Path
from datetime import datetime
import json

def load_guidelines():
    """Carga todos los archivos de guidelines"""
    guidelines_path = Path(__file__).parent.parent / "guidelines"
    
    data = {}
    
    # Cargar session_goals
    with open(guidelines_path / "session_goals.yaml", "r", encoding="utf-8") as f:
        data["goals"] = yaml.safe_load(f)
    
    # Cargar coding_standards
    with open(guidelines_path / "coding_standards.yaml", "r", encoding="utf-8") as f:
        data["standards"] = yaml.safe_load(f)["coding_standards"]
    
    return data

def get_current_objective(data):
    """Obtiene el objetivo de la sesión actual"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    for session in data["goals"]["sessions"]:
        # Convertir fecha a string para comparación
        session_date = session["date"]
        if isinstance(session_date, datetime):
            session_date_str = session_date.strftime("%Y-%m-%d")
        else:
            session_date_str = str(session_date)
        
        if session_date_str == today:
            return session
    
    # Si no hay objetivo para hoy, buscar el primero pendiente
    for session in data["goals"]["sessions"]:
        if session["status"] == "pending":
            return session
    
    return None

def format_prompt(objective, standards):
    """Formatea el prompt para OpenCode"""
    
    # Formatear fecha del objetivo
    objective_date = objective["date"]
    if isinstance(objective_date, datetime):
        date_str = objective_date.strftime("%Y-%m-%d")
    else:
        date_str = str(objective_date)
    
    prompt = f"""
## 🎯 OBJETIVO DE LA SESIÓN ({date_str})

{objective['objective']}

### Prioridad: {objective['priority']}
### Estado: {objective['status']}

### Descripción:
{objective['description']}

### Tareas Pendientes:
"""

    for task in objective["tasks"]:
        if task["status"] != "completed":
            prompt += f"\n⏳ {task['description']}"

    prompt += "\n\n### Dependencias:\n"
    for dep in objective.get("dependencies", []):
        prompt += f"\n⚠️ {dep}"

    prompt += "\n\n### Notas:\n"
    for note in objective.get("notes", []):
        prompt += f"\n📌 {note}"

    prompt += f"""

## 📋 ESTÁNDARES DE CÓDIGO

### Arquitectura:
{standards['description']}

### Capas:
- Domain: {standards['architecture']['layers']['domain']['description']}
- Application: {standards['architecture']['layers']['application']['description']}
- Infrastructure: {standards['architecture']['layers']['infrastructure']['description']}

### Convenciones de nombres:
- Clases: {standards['naming_conventions']['classes'][0]['pattern']}
- Funciones: {standards['naming_conventions']['functions'][0]['pattern']}
- Variables: {standards['naming_conventions']['variables'][0]['pattern']}

### Docstrings: {standards['docstrings']['format']} en {standards['docstrings']['language']}

## 📝 INSTRUCCIONES

1. **Antes de comenzar**: Revisa las tareas pendientes
2. **Durante el desarrollo**: Sigue los estándares de código
3. **Al completar una tarea**: Actualiza con `python scripts/update_task.py --complete <task_id>`
4. **Al finalizar**: Genera reporte con `python scripts/session_report.py`

🚀 ¡Manos a la obra!
"""
    return prompt

def save_context(objective, output_path):
    """Guarda el contexto en JSON para referencia"""
    context = {
        "session_date": datetime.now().isoformat(),
        "objective": {
            "id": objective["id"],
            "title": objective["objective"],
            "priority": objective["priority"],
            "status": objective["status"],
            "pending_tasks": [t for t in objective["tasks"] if t["status"] != "completed"],
            "completed_tasks": [t for t in objective["tasks"] if t["status"] == "completed"]
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(context, f, indent=2, ensure_ascii=False)

def main():
    # Cargar datos
    data = load_guidelines()
    
    # Obtener objetivo actual
    objective = get_current_objective(data)
    
    if not objective:
        print("⚠️ No hay objetivos pendientes para hoy")
        return
    
    # Formatear prompt
    prompt = format_prompt(objective, data["standards"])
    
    # Guardar contexto
    context_path = Path(__file__).parent.parent / "context.json"
    save_context(objective, context_path)
    
    # Mostrar prompt
    print(prompt)
    
    # Guardar también en archivo para referencia
    with open(Path(__file__).parent.parent / "current_prompt.txt", 'w', encoding='utf-8') as f:
        f.write(prompt)
    
    print("\n" + "="*60)
    print("✅ Prompt guardado en project_manager/current_prompt.txt")
    print("📋 Copia el texto arriba y pégalo en OpenCode")

if __name__ == "__main__":
    main()