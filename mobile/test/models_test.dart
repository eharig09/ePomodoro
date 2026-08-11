import 'package:epomodoro_mobile/models.dart';
import 'package:epomodoro_mobile/state/app_controller.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('habit schedule uses Monday-first weekday indexes', () {
    const habit = HabitItem(
      id: 'h1',
      name: 'Workout',
      groupName: 'Health',
      emoji: '💪',
      weekdays: {0, 2, 4},
    );

    expect(habit.isDue(DateTime(2026, 8, 10)), isTrue); // Monday
    expect(habit.isDue(DateTime(2026, 8, 11)), isFalse); // Tuesday
    expect(habit.isDue(DateTime(2026, 8, 12)), isTrue); // Wednesday
  });

  test('local tasks are visible in the due-today view', () {
    const task = TaskItem(
      id: 'local-1',
      title: 'Plan tomorrow',
      project: 'Local',
      priority: 1,
      source: TaskSource.local,
    );

    expect(task.isDueToday, isTrue);
  });

  test('day key is zero padded', () {
    expect(dayKey(DateTime(2026, 2, 3, 18, 30)), '2026-02-03');
  });

  test('an unfinished planned day does not break the current streak early', () {
    final now = DateTime.now();
    final yesterday = now.subtract(const Duration(days: 1));
    final habit = HabitItem(
      id: 'habit-1',
      name: 'Study',
      groupName: 'Learning',
      emoji: '📚',
      weekdays: {yesterday.weekday - 1, now.weekday - 1},
    );
    final controller = AppController()
      ..checkins = [
        HabitCheckin(habitId: habit.id, completedOn: yesterday, source: 'app'),
      ];

    expect(controller.streaksFor(habit).current, 1);
    controller.dispose();
  });
}
