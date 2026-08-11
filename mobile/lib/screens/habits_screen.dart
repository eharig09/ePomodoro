import 'package:flutter/material.dart';

import '../app.dart';
import '../models.dart';

class HabitsScreen extends StatefulWidget {
  const HabitsScreen({super.key});

  @override
  State<HabitsScreen> createState() => _HabitsScreenState();
}

class _HabitsScreenState extends State<HabitsScreen> {
  final _journal = TextEditingController();
  bool _reflectionLoaded = false;
  int _mood = 3;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_reflectionLoaded) {
      final reflection = AppScope.of(context).reflection;
      _mood = reflection.mood;
      _journal.text = reflection.journal;
      _reflectionLoaded = true;
    }
  }

  @override
  void dispose() {
    _journal.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final groups = <String, List<HabitItem>>{};
    for (final habit in controller.habits) {
      groups.putIfAbsent(habit.groupName, () => []).add(habit);
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 32),
      children: [
        Row(
          children: [
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Habits',
                    style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700),
                  ),
                  Text('Streaks count only the days you planned.'),
                ],
              ),
            ),
            FilledButton.tonalIcon(
              onPressed: () => _addHabitDialog(context),
              icon: const Icon(Icons.add),
              label: const Text('Add'),
            ),
          ],
        ),
        const SizedBox(height: 18),
        if (groups.isEmpty)
          const Card(
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'Create a habit with its planned weekdays. Add a Todoist label if any task carrying that label should count for the habit.',
                textAlign: TextAlign.center,
              ),
            ),
          ),
        for (final group in groups.entries) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 14, 4, 6),
            child: Text(
              '${group.value.first.emoji}  ${group.key}',
              style: Theme.of(
                context,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          for (final habit in group.value) _HabitCard(habit: habit),
        ],
        const SizedBox(height: 18),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Mood & quick journal',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 12),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    for (final entry in const [
                      '😞',
                      '😕',
                      '😐',
                      '🙂',
                      '😄',
                    ].indexed)
                      InkWell(
                        borderRadius: BorderRadius.circular(28),
                        onTap: () => setState(() => _mood = entry.$1 + 1),
                        child: AnimatedContainer(
                          duration: const Duration(milliseconds: 150),
                          padding: const EdgeInsets.all(8),
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: _mood == entry.$1 + 1
                                ? Theme.of(context).colorScheme.primaryContainer
                                : Colors.transparent,
                          ),
                          child: Text(
                            entry.$2,
                            style: const TextStyle(fontSize: 26),
                          ),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _journal,
                  minLines: 2,
                  maxLines: 4,
                  decoration: const InputDecoration(
                    labelText: 'A sentence about today',
                    hintText:
                        'What helped, what was hard, or what matters next?',
                  ),
                ),
                const SizedBox(height: 10),
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton(
                    onPressed: () async {
                      await controller.saveReflection(_mood, _journal.text);
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('Today’s reflection saved.'),
                          ),
                        );
                      }
                    },
                    child: const Text('Save reflection'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _addHabitDialog(BuildContext context) async {
    final name = TextEditingController();
    final group = TextEditingController(text: 'Habits');
    final emoji = TextEditingController(text: '✨');
    final label = TextEditingController();
    final weekdays = <int>{0, 1, 2, 3, 4, 5, 6};
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Create habit'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: name,
                  autofocus: true,
                  decoration: const InputDecoration(labelText: 'Habit name'),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    SizedBox(
                      width: 76,
                      child: TextField(
                        controller: emoji,
                        decoration: const InputDecoration(labelText: 'Emoji'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: TextField(
                        controller: group,
                        decoration: const InputDecoration(labelText: 'Group'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: label,
                  decoration: const InputDecoration(
                    labelText: 'Todoist label (optional)',
                    helperText: 'Any completed task with this label counts.',
                  ),
                ),
                const SizedBox(height: 14),
                const Align(
                  alignment: Alignment.centerLeft,
                  child: Text('Planned days · Monday first'),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 4,
                  children: [
                    for (final entry in const [
                      'M',
                      'T',
                      'W',
                      'T',
                      'F',
                      'S',
                      'S',
                    ].indexed)
                      FilterChip(
                        label: Text(entry.$2),
                        selected: weekdays.contains(entry.$1),
                        onSelected: (selected) => setDialogState(() {
                          selected
                              ? weekdays.add(entry.$1)
                              : weekdays.remove(entry.$1);
                        }),
                      ),
                  ],
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                if (name.text.trim().isEmpty || weekdays.isEmpty) return;
                await AppScope.of(context).addHabit(
                  name: name.text,
                  groupName: group.text,
                  emoji: emoji.text,
                  weekdays: weekdays,
                  todoistLabel: label.text,
                );
                if (dialogContext.mounted) Navigator.pop(dialogContext);
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
    name.dispose();
    group.dispose();
    emoji.dispose();
    label.dispose();
  }
}

class _HabitCard extends StatelessWidget {
  const _HabitCard({required this.habit});
  final HabitItem habit;

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final today = DateTime.now();
    final start = DateTime(
      today.year,
      today.month,
      today.day,
    ).subtract(Duration(days: today.weekday - 1));
    final streaks = controller.streaksFor(habit);
    final doneToday = controller.habitDoneOn(habit.id, today);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
        child: Column(
          children: [
            Row(
              children: [
                Checkbox(
                  value: doneToday,
                  onChanged: habit.isDue(today)
                      ? (_) => controller.toggleHabit(habit, today)
                      : null,
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        habit.name,
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      Text(
                        'Current ${streaks.current} · Best ${streaks.best}'
                        '${habit.todoistLabel.isEmpty ? '' : ' · @${habit.todoistLabel}'}',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
                IconButton(
                  tooltip: 'Delete habit',
                  onPressed: () => _confirmDelete(context, habit),
                  icon: const Icon(Icons.more_vert),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                for (final entry in const [
                  'M',
                  'T',
                  'W',
                  'T',
                  'F',
                  'S',
                  'S',
                ].indexed)
                  _DayMark(
                    label: entry.$2,
                    planned: habit.weekdays.contains(entry.$1),
                    day: start.add(Duration(days: entry.$1)),
                    done: controller.habitDoneOn(
                      habit.id,
                      start.add(Duration(days: entry.$1)),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDelete(BuildContext context, HabitItem habit) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete habit?'),
        content: Text(
          'This removes ${habit.name} and its mobile check-in history.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true && context.mounted) {
      await AppScope.of(context).deleteHabit(habit.id);
    }
  }
}

class _DayMark extends StatelessWidget {
  const _DayMark({
    required this.label,
    required this.planned,
    required this.day,
    required this.done,
  });
  final String label;
  final bool planned;
  final DateTime day;
  final bool done;

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now();
    final isFuture = DateTime(
      day.year,
      day.month,
      day.day,
    ).isAfter(DateTime(today.year, today.month, today.day));
    final symbol = !planned
        ? '–'
        : done
        ? '✓'
        : isFuture
        ? '○'
        : '×';
    final color = !planned
        ? Theme.of(context).disabledColor
        : done
        ? Colors.greenAccent
        : isFuture
        ? Theme.of(context).colorScheme.outline
        : Colors.redAccent;
    return Column(
      children: [
        Text(label, style: Theme.of(context).textTheme.labelSmall),
        const SizedBox(height: 3),
        Text(
          symbol,
          style: TextStyle(fontWeight: FontWeight.w700, color: color),
        ),
      ],
    );
  }
}
