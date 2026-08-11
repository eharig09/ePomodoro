enum TaskSource { local, todoist }

class TaskItem {
  const TaskItem({
    required this.id,
    required this.title,
    required this.project,
    required this.priority,
    required this.source,
    this.todoistId,
    this.labels = const [],
    this.dueDate,
    this.completedAt,
  });

  final String id;
  final String title;
  final String project;
  final int priority;
  final TaskSource source;
  final String? todoistId;
  final List<String> labels;
  final DateTime? dueDate;
  final DateTime? completedAt;

  bool get isCompleted => completedAt != null;
  bool get isDueToday {
    if (source == TaskSource.local || dueDate == null) return true;
    final now = DateTime.now();
    final localDue = dueDate!.toLocal();
    return localDue.year == now.year &&
        localDue.month == now.month &&
        localDue.day == now.day;
  }
}

class HabitItem {
  const HabitItem({
    required this.id,
    required this.name,
    required this.groupName,
    required this.emoji,
    required this.weekdays,
    this.todoistLabel = '',
  });

  final String id;
  final String name;
  final String groupName;
  final String emoji;
  final Set<int> weekdays;
  final String todoistLabel;

  bool isDue(DateTime day) => weekdays.contains(day.weekday - 1);
}

class HabitCheckin {
  const HabitCheckin({
    required this.habitId,
    required this.completedOn,
    required this.source,
  });

  final String habitId;
  final DateTime completedOn;
  final String source;
}

class FocusSession {
  const FocusSession({
    required this.id,
    required this.taskName,
    required this.projectName,
    required this.startedAt,
    required this.endedAt,
    required this.plannedMinutes,
    required this.actualSeconds,
    required this.status,
    required this.notes,
  });

  final String id;
  final String taskName;
  final String projectName;
  final DateTime startedAt;
  final DateTime endedAt;
  final int plannedMinutes;
  final int actualSeconds;
  final String status;
  final String notes;

  FocusSession copyWith({String? status, String? notes}) => FocusSession(
    id: id,
    taskName: taskName,
    projectName: projectName,
    startedAt: startedAt,
    endedAt: endedAt,
    plannedMinutes: plannedMinutes,
    actualSeconds: actualSeconds,
    status: status ?? this.status,
    notes: notes ?? this.notes,
  );
}

class DailyReflection {
  const DailyReflection({required this.mood, required this.journal});

  final int mood;
  final String journal;
}

class TodoistCompletedTask {
  const TodoistCompletedTask({
    required this.id,
    required this.content,
    required this.labels,
    required this.completedAt,
  });

  final String id;
  final String content;
  final List<String> labels;
  final DateTime completedAt;
}

String dayKey(DateTime value) {
  final local = value.toLocal();
  return '${local.year.toString().padLeft(4, '0')}-'
      '${local.month.toString().padLeft(2, '0')}-'
      '${local.day.toString().padLeft(2, '0')}';
}

String shortDateTime(DateTime value) {
  final local = value.toLocal();
  final hour = local.hour % 12 == 0 ? 12 : local.hour % 12;
  final minute = local.minute.toString().padLeft(2, '0');
  final suffix = local.hour >= 12 ? 'PM' : 'AM';
  return '${local.month}/${local.day}/${local.year} · $hour:$minute $suffix';
}
