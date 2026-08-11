import 'dart:convert';

import 'package:epomodoro_mobile/data/todoist_client.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('synchronizes active and completed Todoist tasks', () async {
    final client = TodoistClient(
      client: MockClient((request) async {
        expect(request.headers['authorization'], 'Bearer token');
        if (request.url.path.endsWith('/projects')) {
          return http.Response(
            jsonEncode({
              'results': [
                {'id': 'project-1', 'name': 'Learning'},
              ],
              'next_cursor': null,
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/tasks/completed/by_completion_date')) {
          return http.Response(
            jsonEncode({
              'items': [
                {
                  'id': 'done-1',
                  'content': 'Study math',
                  'labels': ['study'],
                  'completed_at': '2026-08-10T12:00:00Z',
                },
              ],
              'next_cursor': null,
            }),
            200,
          );
        }
        if (request.url.path.endsWith('/tasks')) {
          return http.Response(
            jsonEncode({
              'results': [
                {
                  'id': 'task-1',
                  'content': 'Read a chapter',
                  'project_id': 'project-1',
                  'priority': 4,
                  'labels': ['reading'],
                  'due': {'date': '2026-08-10'},
                },
              ],
              'next_cursor': null,
            }),
            200,
          );
        }
        return http.Response('Not found', 404);
      }),
    );

    final result = await client.synchronize('token');

    expect(result.tasks, hasLength(1));
    expect(result.tasks.single.project, 'Learning');
    expect(result.tasks.single.priority, 4);
    expect(result.completed.single.labels, ['study']);
  });

  test('reports rejected tokens clearly', () async {
    final client = TodoistClient(
      client: MockClient((_) async => http.Response('Unauthorized', 401)),
    );

    expect(
      () => client.synchronize('bad-token'),
      throwsA(
        isA<TodoistException>().having(
          (error) => error.message,
          'message',
          contains('rejected'),
        ),
      ),
    );
  });
}
