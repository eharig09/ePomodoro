import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models.dart';

class TodoistException implements Exception {
  const TodoistException(this.message);
  final String message;

  @override
  String toString() => message;
}

class TodoistSyncResult {
  const TodoistSyncResult({required this.tasks, required this.completed});
  final List<TaskItem> tasks;
  final List<TodoistCompletedTask> completed;
}

class TodoistClient {
  TodoistClient({http.Client? client}) : _client = client ?? http.Client();

  static const _baseUrl = 'https://api.todoist.com/api/v1';
  final http.Client _client;

  Future<TodoistSyncResult> synchronize(String token) async {
    final projects = await _projects(token);
    final active = await _paged(token, '/tasks', listKey: 'results');
    final tasks = active.map((raw) {
      final due = raw['due'] as Map<String, dynamic>?;
      final dueValue = due?['date']?.toString();
      final projectId = raw['project_id']?.toString();
      return TaskItem(
        id: 'todoist-${raw['id']}',
        title: raw['content']?.toString() ?? 'Untitled task',
        project: projects[projectId] ?? 'Todoist',
        priority: (raw['priority'] as num?)?.toInt() ?? 1,
        source: TaskSource.todoist,
        todoistId: raw['id']?.toString(),
        labels: (raw['labels'] as List? ?? const [])
            .map((label) => label.toString())
            .toList(),
        dueDate: dueValue == null ? null : DateTime.tryParse(dueValue),
      );
    }).toList();

    final now = DateTime.now().toUtc();
    final since = now.subtract(const Duration(days: 45));
    final completedRaw = await _paged(
      token,
      '/tasks/completed/by_completion_date',
      listKey: 'items',
      query: {
        'since': since.toIso8601String(),
        'until': now.add(const Duration(minutes: 1)).toIso8601String(),
      },
    );
    final completed = completedRaw.map((raw) {
      return TodoistCompletedTask(
        id: raw['id']?.toString() ?? '',
        content: raw['content']?.toString() ?? '',
        labels: (raw['labels'] as List? ?? const [])
            .map((label) => label.toString())
            .toList(),
        completedAt:
            DateTime.tryParse(raw['completed_at']?.toString() ?? '') ??
            DateTime.now().toUtc(),
      );
    }).toList();
    return TodoistSyncResult(tasks: tasks, completed: completed);
  }

  Future<void> closeTask(String token, String taskId) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/tasks/$taskId/close'),
      headers: _headers(token),
    );
    _requireSuccess(response);
  }

  Future<Map<String, String>> _projects(String token) async {
    final rows = await _paged(token, '/projects', listKey: 'results');
    return {
      for (final row in rows)
        if (row['id'] != null)
          row['id'].toString(): row['name']?.toString() ?? 'Todoist',
    };
  }

  Future<List<Map<String, dynamic>>> _paged(
    String token,
    String path, {
    required String listKey,
    Map<String, String> query = const {},
  }) async {
    final results = <Map<String, dynamic>>[];
    String? cursor;
    do {
      final parameters = <String, String>{...query, 'limit': '200'};
      if (cursor != null) parameters['cursor'] = cursor;
      final uri = Uri.parse(
        '$_baseUrl$path',
      ).replace(queryParameters: parameters);
      final response = await _client.get(uri, headers: _headers(token));
      _requireSuccess(response);
      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const TodoistException(
          'Todoist returned an unexpected response.',
        );
      }
      final rows = decoded[listKey] as List? ?? const [];
      results.addAll(
        rows.whereType<Map>().map((row) => row.cast<String, dynamic>()),
      );
      cursor = decoded['next_cursor']?.toString();
      if (cursor != null && cursor.isEmpty) cursor = null;
    } while (cursor != null);
    return results;
  }

  Map<String, String> _headers(String token) => {
    'Authorization': 'Bearer $token',
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  };

  void _requireSuccess(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) return;
    if (response.statusCode == 401 || response.statusCode == 403) {
      throw const TodoistException(
        'Todoist rejected the token. Check it in Settings and try again.',
      );
    }
    throw TodoistException(
      'Todoist request failed (${response.statusCode}). Try again shortly.',
    );
  }
}
