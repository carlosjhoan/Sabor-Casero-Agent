#!/usr/bin/env python
# context_manager/scripts/update_task.py

"""
Actualiza el estado de una tarea.
Uso: python update_task.py --complete T001
     python update_task.py --add "Nueva tarea"
"""

import argparse
import yaml
from pathlib import Path
from datetime import datetime
import shutil

def load_goals():
    guidelines_path = Path(__file__).parent.parent / "guidelines" / "session_goals.yaml"
    with open(guidelines_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_goals(data):
    guidelines_path = Path(__file__).parent.parent / "guidelines" / "session_goals.yaml"
    
    # Crear backup
    backup_path = guidelines_path.with_suffix('.yaml.bak')
    shutil.copy2(guidelines_path, backup_path)
    
    # Guardar
    with open(guidelines_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    
    print(f"✅ Actualizado {guidelines_path}")
    print(f"📋 Backup en {backup_path}")

def find_task(data, task_id):
    for session in data["sessions"]:
        for task in session["tasks"]:
            if task["id"] == task_id:
                return session, task
    return None, None

def add_note_to_session(objective, note):
    if "notes" not in objective:
        objective["notes"] = []
    objective["notes"].append(f"[{datetime.now().strftime('%H:%M')}] {note}")

def main():
    parser = argparse.ArgumentParser(description="Actualizar tareas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--complete", help="ID de tarea completada")
    group.add_argument("--add", help="Añadir nueva tarea")
    group.add_argument("--note", help="Añadir nota a la sesión")
    group.add_argument("--status", choices=["pending", "in_progress", "completed"], help="Cambiar estado del objetivo")
    
    args = parser.parse_args()
    
    data = load_goals()
    
    # Encontrar objetivo actual (fecha de hoy o en progreso)
    from datetime import date
    today = date.today().isoformat()
    current_session = None
    
    for session in data["sessions"]:
        if session.get("date") == today or session.get("status") == "in_progress":
            current_session = session
            break
    
    if not current_session:
        print("⚠️ No hay sesión activa")
        return
    
    if args.complete:
        # Marcar tarea como completada
        session, task = find_task(data, args.complete)
        if task:
            task["status"] = "completed"
            print(f"✅ Tarea {args.complete} completada")
            add_note_to_session(current_session, f"Tarea {args.complete} completada")
        else:
            print(f"⚠️ Tarea {args.complete} no encontrada")
    
    elif args.add:
        # Añadir nueva tarea
        new_id = f"T{len(current_session['tasks']) + 1:03d}"
        current_session["tasks"].append({
            "id": new_id,
            "description": args.add,
            "status": "pending"
        })
        print(f"✅ Nueva tarea añadida: {new_id} - {args.add}")
    
    elif args.note:
        add_note_to_session(current_session, args.note)
        print(f"📝 Nota añadida: {args.note}")
    
    elif args.status:
        current_session["status"] = args.status
        print(f"📊 Estado actualizado a: {args.status}")
    
    # Guardar cambios
    save_goals(data)

if __name__ == "__main__":
    main()