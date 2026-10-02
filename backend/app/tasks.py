import json
import os

TASKS_FILE = os.path.join(os.path.dirname(__file__), "tasks_data.json")

def _load_tasks():
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, "r") as f:
        return json.load(f)

def _save_tasks(tasks):
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

def add_task(title: str, due_date: str = None):
    tasks = _load_tasks()
    new_task = {
        "id": len(tasks) + 1,
        "title": title,
        "due_date": due_date,
        "completed": False
    }
    tasks.append(new_task)
    _save_tasks(tasks)
    return new_task

def list_tasks():
    return _load_tasks()

def complete_task(task_id: int):
    tasks = _load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["completed"] = True
            _save_tasks(tasks)
            return task
    return None

def delete_task(task_id: int):
    tasks = _load_tasks()
    tasks = [t for t in tasks if t["id"] != task_id]
    _save_tasks(tasks)
    return True