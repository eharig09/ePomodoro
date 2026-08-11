import 'dart:convert';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../models.dart';

class LocalStore {
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    final root = await getDatabasesPath();
    _database = await openDatabase(
      p.join(root, 'epomodoro_mobile.db'),
      version: 1,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, _) async {
        await db.execute('''
          CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            project TEXT NOT NULL,
            priority INTEGER NOT NULL,
            source TEXT NOT NULL,
            todoist_id TEXT,
            labels TEXT NOT NULL DEFAULT '[]',
            due_date TEXT,
            completed_at TEXT
          )
        ''');
        await db.execute('''
          CREATE TABLE focus_sessions (
            id TEXT PRIMARY KEY,
            task_name TEXT NOT NULL,
            project_name TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            planned_minutes INTEGER NOT NULL,
            actual_seconds INTEGER NOT NULL,
            status TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
          )
        ''');
        await db.execute('''
          CREATE TABLE habits (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            group_name TEXT NOT NULL,
            emoji TEXT NOT NULL,
            weekdays TEXT NOT NULL,
            todoist_label TEXT NOT NULL DEFAULT ''
          )
        ''');
        await db.execute('''
          CREATE TABLE habit_checkins (
            habit_id TEXT NOT NULL,
            completed_on TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (habit_id, completed_on),
            FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
          )
        ''');
        await db.execute('''
          CREATE TABLE reflections (
            entry_date TEXT PRIMARY KEY,
            mood INTEGER NOT NULL,
            journal TEXT NOT NULL DEFAULT ''
          )
        ''');
        await db.execute('''
          CREATE TABLE app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
          )
        ''');
      },
    );
    return _database!;
  }

  Future<List<TaskItem>> loadTasks() async {
    final db = await database;
    final rows = await db.query(
      'tasks',
      where: 'completed_at IS NULL',
      orderBy: 'project COLLATE NOCASE, priority DESC, title COLLATE NOCASE',
    );
    return rows.map(_taskFromRow).toList();
  }

  Future<void> addLocalTask({
    required String title,
    required String project,
    required int priority,
  }) async {
    final db = await database;
    final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
    await db.insert('tasks', {
      'id': id,
      'title': title,
      'project': project,
      'priority': priority,
      'source': TaskSource.local.name,
      'labels': '[]',
    });
  }

  Future<void> replaceTodoistTasks(List<TaskItem> tasks) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.delete(
        'tasks',
        where: 'source = ? AND completed_at IS NULL',
        whereArgs: [TaskSource.todoist.name],
      );
      for (final task in tasks) {
        await txn.insert(
          'tasks',
          _taskToRow(task),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    });
  }

  Future<void> completeTask(String id, DateTime completedAt) async {
    final db = await database;
    await db.update(
      'tasks',
      {'completed_at': completedAt.toUtc().toIso8601String()},
      where: 'id = ?',
      whereArgs: [id],
    );
  }

  Future<List<FocusSession>> loadSessions() async {
    final db = await database;
    final rows = await db.query('focus_sessions', orderBy: 'started_at DESC');
    return rows.map(_sessionFromRow).toList();
  }

  Future<void> saveSession(FocusSession session) async {
    final db = await database;
    await db.insert(
      'focus_sessions',
      _sessionToRow(session),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> deleteSession(String id) async {
    final db = await database;
    await db.delete('focus_sessions', where: 'id = ?', whereArgs: [id]);
  }

  Future<List<HabitItem>> loadHabits() async {
    final db = await database;
    final rows = await db.query(
      'habits',
      orderBy: 'group_name COLLATE NOCASE, name COLLATE NOCASE',
    );
    return rows.map((row) {
      final weekdays = (jsonDecode(row['weekdays']! as String) as List)
          .map((value) => value as int)
          .toSet();
      return HabitItem(
        id: row['id']! as String,
        name: row['name']! as String,
        groupName: row['group_name']! as String,
        emoji: row['emoji']! as String,
        weekdays: weekdays,
        todoistLabel: row['todoist_label']! as String,
      );
    }).toList();
  }

  Future<void> saveHabit(HabitItem habit) async {
    final db = await database;
    await db.insert('habits', {
      'id': habit.id,
      'name': habit.name,
      'group_name': habit.groupName,
      'emoji': habit.emoji,
      'weekdays': jsonEncode(habit.weekdays.toList()..sort()),
      'todoist_label': habit.todoistLabel,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> deleteHabit(String id) async {
    final db = await database;
    await db.delete('habits', where: 'id = ?', whereArgs: [id]);
  }

  Future<List<HabitCheckin>> loadCheckins() async {
    final db = await database;
    final rows = await db.query('habit_checkins', orderBy: 'completed_on DESC');
    return rows
        .map(
          (row) => HabitCheckin(
            habitId: row['habit_id']! as String,
            completedOn: DateTime.parse(row['completed_on']! as String),
            source: row['source']! as String,
          ),
        )
        .toList();
  }

  Future<void> setHabitCheckin({
    required String habitId,
    required DateTime day,
    required bool completed,
    required String source,
  }) async {
    final db = await database;
    if (completed) {
      await db.insert('habit_checkins', {
        'habit_id': habitId,
        'completed_on': dayKey(day),
        'source': source,
      }, conflictAlgorithm: ConflictAlgorithm.ignore);
    } else {
      await db.delete(
        'habit_checkins',
        where: 'habit_id = ? AND completed_on = ?',
        whereArgs: [habitId, dayKey(day)],
      );
    }
  }

  Future<DailyReflection?> loadReflection(DateTime day) async {
    final db = await database;
    final rows = await db.query(
      'reflections',
      where: 'entry_date = ?',
      whereArgs: [dayKey(day)],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return DailyReflection(
      mood: rows.first['mood']! as int,
      journal: rows.first['journal']! as String,
    );
  }

  Future<void> saveReflection(DateTime day, DailyReflection reflection) async {
    final db = await database;
    await db.insert('reflections', {
      'entry_date': dayKey(day),
      'mood': reflection.mood,
      'journal': reflection.journal,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<String?> getSetting(String key) async {
    final db = await database;
    final rows = await db.query(
      'app_settings',
      columns: ['setting_value'],
      where: 'setting_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first['setting_value']! as String;
  }

  Future<void> setSetting(String key, String value) async {
    final db = await database;
    await db.insert('app_settings', {
      'setting_key': key,
      'setting_value': value,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> deleteSetting(String key) async {
    final db = await database;
    await db.delete('app_settings', where: 'setting_key = ?', whereArgs: [key]);
  }

  TaskItem _taskFromRow(Map<String, Object?> row) => TaskItem(
    id: row['id']! as String,
    title: row['title']! as String,
    project: row['project']! as String,
    priority: row['priority']! as int,
    source: TaskSource.values.byName(row['source']! as String),
    todoistId: row['todoist_id'] as String?,
    labels: (jsonDecode(row['labels']! as String) as List).cast<String>(),
    dueDate: row['due_date'] == null
        ? null
        : DateTime.parse(row['due_date']! as String),
    completedAt: row['completed_at'] == null
        ? null
        : DateTime.parse(row['completed_at']! as String),
  );

  Map<String, Object?> _taskToRow(TaskItem task) => {
    'id': task.id,
    'title': task.title,
    'project': task.project,
    'priority': task.priority,
    'source': task.source.name,
    'todoist_id': task.todoistId,
    'labels': jsonEncode(task.labels),
    'due_date': task.dueDate?.toIso8601String(),
    'completed_at': task.completedAt?.toUtc().toIso8601String(),
  };

  FocusSession _sessionFromRow(Map<String, Object?> row) => FocusSession(
    id: row['id']! as String,
    taskName: row['task_name']! as String,
    projectName: row['project_name']! as String,
    startedAt: DateTime.parse(row['started_at']! as String),
    endedAt: DateTime.parse(row['ended_at']! as String),
    plannedMinutes: row['planned_minutes']! as int,
    actualSeconds: row['actual_seconds']! as int,
    status: row['status']! as String,
    notes: row['notes']! as String,
  );

  Map<String, Object?> _sessionToRow(FocusSession session) => {
    'id': session.id,
    'task_name': session.taskName,
    'project_name': session.projectName,
    'started_at': session.startedAt.toUtc().toIso8601String(),
    'ended_at': session.endedAt.toUtc().toIso8601String(),
    'planned_minutes': session.plannedMinutes,
    'actual_seconds': session.actualSeconds,
    'status': session.status,
    'notes': session.notes,
  };
}
