import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../data/local_store.dart';
import '../data/todoist_client.dart';
import '../models.dart';
import '../services/chime_service.dart';

class AppController extends ChangeNotifier {
  AppController({
    LocalStore? store,
    TodoistClient? todoist,
    FlutterSecureStorage? secureStorage,
    ChimeService? chime,
  }) : store = store ?? LocalStore(),
       todoist = todoist ?? TodoistClient(),
       secureStorage = secureStorage ?? const FlutterSecureStorage(),
       chime = chime ?? ChimeService();

  static const _tokenKey = 'todoist_api_token';
  static const _activeTimerKey = 'active_timer';

  final LocalStore store;
  final TodoistClient todoist;
  final FlutterSecureStorage secureStorage;
  final ChimeService chime;

  List<TaskItem> tasks = [];
  List<HabitItem> habits = [];
  List<HabitCheckin> checkins = [];
  List<FocusSession> sessions = [];
  DailyReflection reflection = const DailyReflection(mood: 3, journal: '');
  bool loading = true;
  bool syncing = false;
  bool darkMode = true;
  bool chimeEnabled = true;
  bool hasTodoistToken = false;
  String? message;
  DateTime? lastSync;

  TaskItem? timerTask;
  int timerMinutes = 25;
  int remainingSeconds = 25 * 60;
  bool timerRunning = false;
  bool timerIsBreak = false;
  DateTime? timerStartedAt;
  DateTime? timerEndAt;
  Timer? _ticker;
  int _ticksSinceSave = 0;

  Future<void> initialize() async {
    loading = true;
    notifyListeners();
    try {
      await reload();
      darkMode = (await store.getSetting('dark_mode')) != 'false';
      chimeEnabled = (await store.getSetting('chime_enabled')) != 'false';
      final syncValue = await store.getSetting('last_sync');
      lastSync = syncValue == null ? null : DateTime.tryParse(syncValue);
      hasTodoistToken =
          (await secureStorage.read(key: _tokenKey) ?? '').isNotEmpty;
      await _restoreTimer();
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> reload() async {
    tasks = await store.loadTasks();
    habits = await store.loadHabits();
    checkins = await store.loadCheckins();
    sessions = await store.loadSessions();
    reflection =
        await store.loadReflection(DateTime.now()) ??
        const DailyReflection(mood: 3, journal: '');
    notifyListeners();
  }

  Future<void> addLocalTask(String title, String project, int priority) async {
    await store.addLocalTask(
      title: title,
      project: project,
      priority: priority,
    );
    tasks = await store.loadTasks();
    notifyListeners();
  }

  Future<void> completeTask(TaskItem task) async {
    message = null;
    try {
      if (task.todoistId != null) {
        final token = await secureStorage.read(key: _tokenKey);
        if (token == null || token.isEmpty) {
          throw const TodoistException('Connect Todoist in Settings first.');
        }
        await todoist.closeTask(token, task.todoistId!);
      }
      final now = DateTime.now();
      await store.completeTask(task.id, now);
      await _matchHabitCompletion(
        content: task.title,
        labels: task.labels,
        completedAt: now,
        source: task.source.name,
      );
      await reload();
    } on TodoistException catch (error) {
      message = error.message;
      notifyListeners();
      rethrow;
    }
  }

  Future<void> saveTodoistToken(String token) async {
    final clean = token.trim();
    if (clean.isEmpty) {
      await secureStorage.delete(key: _tokenKey);
      hasTodoistToken = false;
      message = 'Todoist disconnected. Local mode remains available.';
    } else {
      await secureStorage.write(key: _tokenKey, value: clean);
      hasTodoistToken = true;
      message = 'Todoist token saved securely.';
    }
    notifyListeners();
  }

  Future<String> readTodoistToken() async =>
      await secureStorage.read(key: _tokenKey) ?? '';

  Future<void> syncTodoist() async {
    if (syncing) return;
    final token = await secureStorage.read(key: _tokenKey) ?? '';
    if (token.isEmpty) {
      message = 'Add your Todoist API token in Settings first.';
      notifyListeners();
      return;
    }
    syncing = true;
    message = null;
    notifyListeners();
    try {
      final result = await todoist.synchronize(token);
      await store.replaceTodoistTasks(result.tasks);
      for (final completed in result.completed) {
        await _matchHabitCompletion(
          content: completed.content,
          labels: completed.labels,
          completedAt: completed.completedAt,
          source: 'todoist',
        );
      }
      lastSync = DateTime.now();
      await store.setSetting('last_sync', lastSync!.toIso8601String());
      await reload();
      message = 'Todoist synced: ${result.tasks.length} active tasks.';
    } on TodoistException catch (error) {
      message = error.message;
    } catch (_) {
      message = 'Could not reach Todoist. Your local data is safe.';
    } finally {
      syncing = false;
      notifyListeners();
    }
  }

  Future<void> addHabit({
    required String name,
    required String groupName,
    required String emoji,
    required Set<int> weekdays,
    required String todoistLabel,
  }) async {
    final habit = HabitItem(
      id: 'habit-${DateTime.now().microsecondsSinceEpoch}',
      name: name.trim(),
      groupName: groupName.trim().isEmpty ? 'Habits' : groupName.trim(),
      emoji: emoji.trim().isEmpty ? '✨' : emoji.trim(),
      weekdays: weekdays,
      todoistLabel: todoistLabel.trim(),
    );
    await store.saveHabit(habit);
    habits = await store.loadHabits();
    notifyListeners();
  }

  Future<void> deleteHabit(String id) async {
    await store.deleteHabit(id);
    await reload();
  }

  bool habitDoneOn(String habitId, DateTime day) => checkins.any(
    (checkin) =>
        checkin.habitId == habitId &&
        dayKey(checkin.completedOn) == dayKey(day),
  );

  Future<void> toggleHabit(HabitItem habit, DateTime day) async {
    await store.setHabitCheckin(
      habitId: habit.id,
      day: day,
      completed: !habitDoneOn(habit.id, day),
      source: 'app',
    );
    checkins = await store.loadCheckins();
    notifyListeners();
  }

  ({int current, int best}) streaksFor(HabitItem habit) {
    final done = checkins
        .where((checkin) => checkin.habitId == habit.id)
        .map((checkin) => dayKey(checkin.completedOn))
        .toSet();
    if (done.isEmpty) return (current: 0, best: 0);
    final earliest = checkins
        .where((checkin) => checkin.habitId == habit.id)
        .map((checkin) => checkin.completedOn)
        .reduce((a, b) => a.isBefore(b) ? a : b);
    final today = DateTime.now();
    var cursor = DateTime(earliest.year, earliest.month, earliest.day);
    final end = DateTime(today.year, today.month, today.day);
    var run = 0;
    var best = 0;
    var lastRun = 0;
    while (!cursor.isAfter(end)) {
      if (habit.isDue(cursor)) {
        if (done.contains(dayKey(cursor))) {
          run++;
          if (run > best) best = run;
        } else if (dayKey(cursor) == dayKey(end)) {
          // The current planned day is still in progress, so it does not break
          // a streak until the next day arrives.
        } else {
          run = 0;
        }
        lastRun = run;
      }
      cursor = cursor.add(const Duration(days: 1));
    }
    return (current: lastRun, best: best);
  }

  Future<void> saveReflection(int mood, String journal) async {
    reflection = DailyReflection(mood: mood, journal: journal.trim());
    await store.saveReflection(DateTime.now(), reflection);
    notifyListeners();
  }

  Future<void> updateSession(FocusSession session) async {
    await store.saveSession(session);
    sessions = await store.loadSessions();
    notifyListeners();
  }

  Future<void> deleteSession(String id) async {
    await store.deleteSession(id);
    sessions = await store.loadSessions();
    notifyListeners();
  }

  Future<void> setDarkMode(bool value) async {
    darkMode = value;
    await store.setSetting('dark_mode', value.toString());
    notifyListeners();
  }

  Future<void> setChimeEnabled(bool value) async {
    chimeEnabled = value;
    await store.setSetting('chime_enabled', value.toString());
    notifyListeners();
  }

  void configureTimer({TaskItem? task, int? minutes, bool? isBreak}) {
    if (timerRunning) return;
    if (task != null) timerTask = task;
    if (minutes != null) {
      timerMinutes = minutes;
      remainingSeconds = minutes * 60;
    }
    if (isBreak != null) timerIsBreak = isBreak;
    notifyListeners();
    unawaited(_persistTimer());
  }

  Future<void> startTimer() async {
    if (timerRunning) return;
    if (!timerIsBreak && timerTask == null) {
      message = 'Choose a task before starting focus.';
      notifyListeners();
      return;
    }
    timerStartedAt ??= DateTime.now();
    timerEndAt = DateTime.now().add(Duration(seconds: remainingSeconds));
    timerRunning = true;
    _startTicker();
    await _persistTimer();
    notifyListeners();
  }

  Future<void> pauseTimer() async {
    if (!timerRunning) return;
    _updateRemaining();
    timerRunning = false;
    timerEndAt = null;
    _ticker?.cancel();
    await _persistTimer();
    notifyListeners();
  }

  Future<void> finishTimer(String status, {String notes = ''}) async {
    _ticker?.cancel();
    if (timerRunning) _updateRemaining();
    final started = timerStartedAt;
    final planned = timerMinutes;
    final actual = (planned * 60 - remainingSeconds).clamp(0, planned * 60);
    final wasBreak = timerIsBreak;
    final task = timerTask;
    timerRunning = false;
    timerEndAt = null;
    timerStartedAt = null;
    remainingSeconds = timerMinutes * 60;
    await store.deleteSetting(_activeTimerKey);
    if (!wasBreak && started != null && task != null && actual > 0) {
      await store.saveSession(
        FocusSession(
          id: 'session-${DateTime.now().microsecondsSinceEpoch}',
          taskName: task.title,
          projectName: task.project,
          startedAt: started,
          endedAt: DateTime.now(),
          plannedMinutes: planned,
          actualSeconds: actual,
          status: status,
          notes: notes.trim(),
        ),
      );
      sessions = await store.loadSessions();
    }
    if (status == 'completed' && chimeEnabled) {
      unawaited(chime.play());
    }
    notifyListeners();
  }

  Future<void> checkpointTimer() => _persistTimer();

  void _startTicker() {
    _ticker?.cancel();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) async {
      _updateRemaining();
      _ticksSinceSave++;
      if (_ticksSinceSave >= 5) {
        _ticksSinceSave = 0;
        await _persistTimer();
      }
      if (remainingSeconds <= 0) {
        await finishTimer('completed');
      } else {
        notifyListeners();
      }
    });
  }

  void _updateRemaining() {
    if (timerEndAt == null) return;
    remainingSeconds = timerEndAt!
        .difference(DateTime.now())
        .inSeconds
        .clamp(0, timerMinutes * 60);
  }

  Future<void> _persistTimer() async {
    if (timerStartedAt == null && !timerRunning) return;
    await store.setSetting(
      _activeTimerKey,
      jsonEncode({
        'task_id': timerTask?.id,
        'minutes': timerMinutes,
        'remaining': remainingSeconds,
        'running': timerRunning,
        'is_break': timerIsBreak,
        'started_at': timerStartedAt?.toIso8601String(),
        'end_at': timerEndAt?.toIso8601String(),
      }),
    );
  }

  Future<void> _restoreTimer() async {
    final raw = await store.getSetting(_activeTimerKey);
    if (raw == null) return;
    try {
      final data = jsonDecode(raw) as Map<String, dynamic>;
      timerMinutes = data['minutes'] as int? ?? 25;
      remainingSeconds = data['remaining'] as int? ?? timerMinutes * 60;
      timerRunning = data['running'] as bool? ?? false;
      timerIsBreak = data['is_break'] as bool? ?? false;
      timerStartedAt = DateTime.tryParse(data['started_at']?.toString() ?? '');
      timerEndAt = DateTime.tryParse(data['end_at']?.toString() ?? '');
      final taskId = data['task_id']?.toString();
      timerTask = tasks.where((task) => task.id == taskId).firstOrNull;
      if (timerRunning && timerEndAt != null) {
        _updateRemaining();
        if (remainingSeconds <= 0) {
          await finishTimer('completed');
        } else {
          _startTicker();
        }
      }
    } catch (_) {
      await store.deleteSetting(_activeTimerKey);
    }
  }

  Future<void> _matchHabitCompletion({
    required String content,
    required List<String> labels,
    required DateTime completedAt,
    required String source,
  }) async {
    final foldedLabels = labels.map((label) => label.toLowerCase()).toSet();
    for (final habit in habits) {
      final labelMatch =
          habit.todoistLabel.isNotEmpty &&
          foldedLabels.contains(habit.todoistLabel.toLowerCase());
      final nameMatch = habit.name.toLowerCase() == content.toLowerCase();
      if (labelMatch || nameMatch) {
        await store.setHabitCheckin(
          habitId: habit.id,
          day: completedAt.toLocal(),
          completed: true,
          source: source,
        );
      }
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    unawaited(chime.dispose());
    super.dispose();
  }
}
