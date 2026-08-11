import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';

import '../models.dart';

class LocalStore {
  Database? _database;
  String? _profileId;

  String get profileKey => _profileId ?? 'local';

  String get _databaseFileName => _profileId == null
      ? 'epomodoro_mobile.db'
      : 'epomodoro_${_profileId!}.db';

  Future<Database> get database async {
    if (_database != null) return _database!;
    final root = await getDatabasesPath();
    _database = await openDatabase(
      p.join(root, _databaseFileName),
      version: 2,
      onConfigure: (db) => db.execute('PRAGMA foreign_keys = ON'),
      onCreate: (db, _) => _createSchema(db),
      onUpgrade: (db, oldVersion, _) async {
        if (oldVersion < 2) {
          await db.execute('ALTER TABLE tasks ADD COLUMN created_at TEXT');
          await db.execute('ALTER TABLE habits ADD COLUMN created_at TEXT');
          await db.execute('ALTER TABLE habits ADD COLUMN updated_at TEXT');
          await db.execute(
            'ALTER TABLE habit_checkins ADD COLUMN completed_at TEXT',
          );
          await db.execute(
            'ALTER TABLE habit_checkins ADD COLUMN todoist_task_id TEXT',
          );
          await db.execute(
            'ALTER TABLE habit_checkins ADD COLUMN todoist_task_name TEXT',
          );
          await db.execute(
            'ALTER TABLE reflections ADD COLUMN updated_at TEXT',
          );
          await _createSyncTables(db);
        }
      },
    );
    return _database!;
  }

  Future<void> _createSchema(Database db) async {
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
            completed_at TEXT,
            created_at TEXT
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
            todoist_label TEXT NOT NULL DEFAULT '',
            created_at TEXT,
            updated_at TEXT
          )
        ''');
    await db.execute('''
          CREATE TABLE habit_checkins (
            habit_id TEXT NOT NULL,
            completed_on TEXT NOT NULL,
            source TEXT NOT NULL,
            completed_at TEXT,
            todoist_task_id TEXT,
            todoist_task_name TEXT,
            PRIMARY KEY (habit_id, completed_on),
            FOREIGN KEY (habit_id) REFERENCES habits(id) ON DELETE CASCADE
          )
        ''');
    await db.execute('''
          CREATE TABLE reflections (
            entry_date TEXT PRIMARY KEY,
            mood INTEGER NOT NULL,
            journal TEXT NOT NULL DEFAULT '',
            updated_at TEXT
          )
        ''');
    await db.execute('''
          CREATE TABLE app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
          )
        ''');
    await _createSyncTables(db);
  }

  Future<void> _createSyncTables(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS cloud_sync_shadow (
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        client_updated_at TEXT NOT NULL,
        device_id TEXT NOT NULL,
        deleted_at TEXT,
        PRIMARY KEY (entity_type, entity_id)
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS cloud_sync_state (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
      )
    ''');
  }

  Future<void> useProfile(String? userId, {bool importLocal = false}) async {
    final cleanId = userId?.trim();
    if (cleanId != null &&
        !RegExp(
          r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$',
        ).hasMatch(cleanId)) {
      throw const FormatException('Invalid account profile identifier.');
    }
    await _database?.close();
    _database = null;
    final root = await getDatabasesPath();
    final localPath = p.join(root, 'epomodoro_mobile.db');
    final targetPath = cleanId == null
        ? localPath
        : p.join(root, 'epomodoro_$cleanId.db');
    if (importLocal && cleanId != null && !await databaseExists(targetPath)) {
      if (await databaseExists(localPath)) {
        await File(localPath).copy(targetPath);
      }
    }
    _profileId = cleanId;
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
      'created_at': DateTime.now().toUtc().toIso8601String(),
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
    final now = DateTime.now().toUtc().toIso8601String();
    final existing = await db.query(
      'habits',
      columns: ['created_at'],
      where: 'id = ?',
      whereArgs: [habit.id],
      limit: 1,
    );
    await db.insert('habits', {
      'id': habit.id,
      'name': habit.name,
      'group_name': habit.groupName,
      'emoji': habit.emoji,
      'weekdays': jsonEncode(habit.weekdays.toList()..sort()),
      'todoist_label': habit.todoistLabel,
      'created_at': existing.isEmpty
          ? now
          : existing.first['created_at'] ?? now,
      'updated_at': now,
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
        'completed_at': DateTime.now().toUtc().toIso8601String(),
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
      'updated_at': DateTime.now().toUtc().toIso8601String(),
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

  Future<List<Map<String, Object?>>> exportSyncEntities() async {
    final db = await database;
    final entities = <Map<String, Object?>>[];
    final tasks = await db.query(
      'tasks',
      where: 'source = ?',
      whereArgs: [TaskSource.local.name],
    );
    for (final row in tasks) {
      entities.add({
        'entity_type': 'local_task',
        'entity_id': row['id'],
        'payload': {
          'title': row['title'],
          'description': '',
          'project': row['project'],
          'priority': row['priority'],
          'created_at': row['created_at'] ?? '1970-01-01T00:00:00.000Z',
          'completed_at': row['completed_at'],
        },
      });
    }
    for (final row in await db.query('focus_sessions')) {
      entities.add({
        'entity_type': 'focus_session',
        'entity_id': row['id'],
        'payload': {
          'task_name': row['task_name'],
          'project_name': row['project_name'],
          'todoist_task_id': 'local:${row['id']}',
          'project_id': null,
          'started_at': row['started_at'],
          'ended_at': row['ended_at'],
          'planned_minutes': row['planned_minutes'],
          'actual_seconds': row['actual_seconds'],
          'status': row['status'],
          'notes': row['notes'],
          'created_at': row['started_at'],
          'is_provisional': false,
        },
      });
    }
    for (final row in await db.query('habits')) {
      final label = row['todoist_label']?.toString() ?? '';
      entities.add({
        'entity_type': 'habit',
        'entity_id': row['id'],
        'payload': {
          'name': row['name'],
          'group_name': row['group_name'],
          'emoji': row['emoji'],
          'weekdays': jsonDecode(row['weekdays']! as String),
          'todoist_labels': label.isEmpty ? <String>[] : [label],
          'task_links': <Object?>[],
          'is_active': true,
          'created_at': row['created_at'] ?? '1970-01-01T00:00:00.000Z',
          'updated_at': row['updated_at'] ?? '1970-01-01T00:00:00.000Z',
        },
      });
    }
    for (final row in await db.query('habit_checkins')) {
      final habitId = row['habit_id']! as String;
      final completedOn = row['completed_on']! as String;
      entities.add({
        'entity_type': 'habit_checkin',
        'entity_id': '$habitId:$completedOn',
        'payload': {
          'habit_id': habitId,
          'completed_on': completedOn,
          'completed_at': row['completed_at'] ?? '${completedOn}T12:00:00.000Z',
          'source': row['source'],
          'todoist_task_id': row['todoist_task_id'],
          'todoist_task_name': row['todoist_task_name'],
        },
      });
    }
    for (final row in await db.query('reflections')) {
      entities.add({
        'entity_type': 'reflection',
        'entity_id': row['entry_date'],
        'payload': {
          'entry_date': row['entry_date'],
          'mood': row['mood'],
          'journal': row['journal'],
          'updated_at':
              row['updated_at'] ?? '${row['entry_date']}T12:00:00.000Z',
        },
      });
    }
    return entities;
  }

  Future<List<Map<String, Object?>>> loadCloudShadow() async {
    final db = await database;
    return db.query('cloud_sync_shadow');
  }

  Future<String?> getCloudState(String key) async {
    final db = await database;
    final rows = await db.query(
      'cloud_sync_state',
      columns: ['setting_value'],
      where: 'setting_key = ?',
      whereArgs: [key],
      limit: 1,
    );
    return rows.isEmpty ? null : rows.first['setting_value']! as String;
  }

  Future<void> setCloudState(String key, String value) async {
    final db = await database;
    await db.insert('cloud_sync_state', {
      'setting_key': key,
      'setting_value': value,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> applyCloudRecords(List<Map<String, Object?>> records) async {
    final db = await database;
    await db.transaction((txn) async {
      for (final record in records) {
        final type = record['entity_type']! as String;
        final id = record['entity_id']! as String;
        final payload = (record['payload']! as Map).map(
          (key, value) => MapEntry('$key', value),
        );
        if (record['deleted_at'] != null) {
          await _deleteCloudEntity(txn, type, id, payload);
        } else {
          await _upsertCloudEntity(txn, type, id, payload);
        }
        await txn.insert('cloud_sync_shadow', {
          'entity_type': type,
          'entity_id': id,
          'payload_json': record['payload_json'],
          'client_updated_at': record['client_updated_at'],
          'device_id': record['device_id'],
          'deleted_at': record['deleted_at'],
        }, conflictAlgorithm: ConflictAlgorithm.replace);
      }
    });
  }

  Future<void> _deleteCloudEntity(
    DatabaseExecutor db,
    String type,
    String id,
    Map<String, Object?> payload,
  ) async {
    switch (type) {
      case 'local_task':
        await db.delete('tasks', where: 'id = ?', whereArgs: [id]);
        break;
      case 'focus_session':
        await db.delete('focus_sessions', where: 'id = ?', whereArgs: [id]);
        break;
      case 'habit':
        await db.delete('habits', where: 'id = ?', whereArgs: [id]);
        break;
      case 'habit_checkin':
        final separator = id.lastIndexOf(':');
        final habitId =
            payload['habit_id']?.toString() ??
            (separator < 0 ? '' : id.substring(0, separator));
        final completedOn =
            payload['completed_on']?.toString() ??
            (separator < 0 ? '' : id.substring(separator + 1));
        await db.delete(
          'habit_checkins',
          where: 'habit_id = ? AND completed_on = ?',
          whereArgs: [habitId, completedOn],
        );
        break;
      case 'reflection':
        await db.delete(
          'reflections',
          where: 'entry_date = ?',
          whereArgs: [id],
        );
        break;
    }
  }

  Future<void> _upsertCloudEntity(
    DatabaseExecutor db,
    String type,
    String id,
    Map<String, Object?> payload,
  ) async {
    switch (type) {
      case 'local_task':
        await db.insert('tasks', {
          'id': id,
          'title': payload['title']?.toString() ?? 'Untitled task',
          'project': payload['project']?.toString() ?? 'Local',
          'priority': _boundedInt(payload['priority'], 1, 4, 1),
          'source': TaskSource.local.name,
          'labels': '[]',
          'completed_at': payload['completed_at']?.toString(),
          'created_at': payload['created_at']?.toString(),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        break;
      case 'focus_session':
        await db.insert('focus_sessions', {
          'id': id,
          'task_name': payload['task_name']?.toString() ?? 'Focus session',
          'project_name': payload['project_name']?.toString() ?? 'Local',
          'started_at': payload['started_at']?.toString(),
          'ended_at': payload['ended_at']?.toString(),
          'planned_minutes': _boundedInt(
            payload['planned_minutes'],
            1,
            1440,
            25,
          ),
          'actual_seconds': _boundedInt(
            payload['actual_seconds'],
            0,
            604800,
            0,
          ),
          'status': _sessionStatus(payload['status']),
          'notes': payload['notes']?.toString() ?? '',
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        break;
      case 'habit':
        final weekdays = payload['weekdays'] is List
            ? (payload['weekdays']! as List)
                  .map((value) => int.tryParse('$value'))
                  .whereType<int>()
                  .where((value) => value >= 0 && value <= 6)
                  .toSet()
                  .toList()
            : List<int>.generate(7, (index) => index);
        weekdays.sort();
        final labels = payload['todoist_labels'];
        await db.insert('habits', {
          'id': id,
          'name': payload['name']?.toString() ?? 'Habit',
          'group_name': payload['group_name']?.toString() ?? 'Habits',
          'emoji': payload['emoji']?.toString() ?? '✨',
          'weekdays': jsonEncode(
            weekdays.isEmpty
                ? List<int>.generate(7, (index) => index)
                : weekdays,
          ),
          'todoist_label': labels is List && labels.isNotEmpty
              ? labels.first.toString()
              : payload['todoist_label']?.toString() ?? '',
          'created_at': payload['created_at']?.toString(),
          'updated_at': payload['updated_at']?.toString(),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        break;
      case 'habit_checkin':
        final habitId = payload['habit_id']?.toString() ?? '';
        final completedOn = payload['completed_on']?.toString() ?? '';
        if (habitId.isEmpty || completedOn.isEmpty) return;
        final habit = await db.query(
          'habits',
          columns: ['id'],
          where: 'id = ?',
          whereArgs: [habitId],
          limit: 1,
        );
        if (habit.isEmpty) return;
        await db.insert('habit_checkins', {
          'habit_id': habitId,
          'completed_on': completedOn,
          'source': payload['source']?.toString() ?? 'cloud',
          'completed_at': payload['completed_at']?.toString(),
          'todoist_task_id': payload['todoist_task_id']?.toString(),
          'todoist_task_name': payload['todoist_task_name']?.toString(),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        break;
      case 'reflection':
        final entryDate = payload['entry_date']?.toString() ?? id;
        await db.insert('reflections', {
          'entry_date': entryDate,
          'mood': _boundedInt(payload['mood'], 1, 5, 3),
          'journal': payload['journal']?.toString() ?? '',
          'updated_at': payload['updated_at']?.toString(),
        }, conflictAlgorithm: ConflictAlgorithm.replace);
        break;
    }
  }

  int _boundedInt(Object? value, int minimum, int maximum, int fallback) {
    final parsed = int.tryParse('$value');
    if (parsed == null) return fallback;
    return parsed.clamp(minimum, maximum);
  }

  String _sessionStatus(Object? value) {
    final status = value?.toString() ?? '';
    return const {
          'completed',
          'continue',
          'interrupted',
          'abandoned',
        }.contains(status)
        ? status
        : 'continue';
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
