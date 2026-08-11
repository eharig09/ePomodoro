import 'package:flutter/material.dart';

import '../app.dart';
import '../models.dart';

class TodayScreen extends StatefulWidget {
  const TodayScreen({required this.onFocusTask, super.key});

  final ValueChanged<TaskItem> onFocusTask;

  @override
  State<TodayScreen> createState() => _TodayScreenState();
}

class _TodayScreenState extends State<TodayScreen> {
  bool _showAll = false;

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final visible =
        controller.tasks.where((task) => _showAll || task.isDueToday).toList()
          ..sort((a, b) {
            final project = a.project.toLowerCase().compareTo(
              b.project.toLowerCase(),
            );
            if (project != 0) return project;
            final priority = b.priority.compareTo(a.priority);
            return priority != 0
                ? priority
                : a.title.toLowerCase().compareTo(b.title.toLowerCase());
          });
    final grouped = <String, List<TaskItem>>{};
    for (final task in visible) {
      grouped.putIfAbsent(task.project, () => []).add(task);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 12, 8),
          child: Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Today',
                      style: TextStyle(
                        fontSize: 30,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    Text('Projects side by side · highest priority first'),
                  ],
                ),
              ),
              IconButton.filledTonal(
                tooltip: 'Add local task',
                onPressed: () => showAddTaskDialog(context),
                icon: const Icon(Icons.add),
              ),
              const SizedBox(width: 6),
              IconButton.filledTonal(
                tooltip: 'Sync Todoist',
                onPressed: controller.syncing
                    ? null
                    : () async {
                        await controller.syncTodoist();
                        if (context.mounted && controller.message != null) {
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(controller.message!)),
                          );
                        }
                      },
                icon: controller.syncing
                    ? const SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.sync),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('Due today')),
                  ButtonSegment(value: true, label: Text('All active')),
                ],
                selected: {_showAll},
                onSelectionChanged: (value) =>
                    setState(() => _showAll = value.first),
              ),
              const SizedBox(height: 8),
              Text(
                _showAll
                    ? '${visible.length} active task${visible.length == 1 ? '' : 's'}'
                    : '${visible.length} task${visible.length == 1 ? '' : 's'} due today',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
        ),
        Expanded(
          child: grouped.isEmpty
              ? _EmptyTasks(
                  hasTodoist: controller.hasTodoistToken,
                  dueToday: !_showAll,
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                  scrollDirection: Axis.horizontal,
                  itemCount: grouped.length,
                  separatorBuilder: (context, index) =>
                      const SizedBox(width: 12),
                  itemBuilder: (context, index) {
                    final entry = grouped.entries.elementAt(index);
                    return SizedBox(
                      width:
                          MediaQuery.sizeOf(context).width.clamp(280, 360) - 32,
                      child: Card(
                        clipBehavior: Clip.antiAlias,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              padding: const EdgeInsets.fromLTRB(
                                16,
                                16,
                                16,
                                10,
                              ),
                              child: Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      entry.key,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleLarge
                                          ?.copyWith(
                                            fontWeight: FontWeight.w700,
                                          ),
                                    ),
                                  ),
                                  Badge(label: Text('${entry.value.length}')),
                                ],
                              ),
                            ),
                            const Divider(height: 1),
                            Expanded(
                              child: ListView.builder(
                                itemCount: entry.value.length,
                                itemBuilder: (context, taskIndex) => _TaskTile(
                                  task: entry.value[taskIndex],
                                  onFocus: () => widget.onFocusTask(
                                    entry.value[taskIndex],
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class _TaskTile extends StatelessWidget {
  const _TaskTile({required this.task, required this.onFocus});

  final TaskItem task;
  final VoidCallback onFocus;

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final priorityColor = switch (task.priority) {
      4 => Colors.redAccent,
      3 => Colors.orangeAccent,
      2 => Colors.blueAccent,
      _ => Theme.of(context).colorScheme.outline,
    };
    return ListTile(
      contentPadding: const EdgeInsets.only(left: 8, right: 4),
      leading: IconButton(
        tooltip: 'Complete',
        onPressed: () async {
          try {
            await controller.completeTask(task);
          } catch (_) {
            if (context.mounted) {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                    controller.message ?? 'Could not complete task.',
                  ),
                ),
              );
            }
          }
        },
        icon: Icon(Icons.radio_button_unchecked, color: priorityColor),
      ),
      title: Text(task.title),
      subtitle: Text(
        task.source == TaskSource.todoist
            ? 'Todoist · P${5 - task.priority}'
            : 'Local task',
      ),
      trailing: IconButton(
        tooltip: 'Focus on this task',
        onPressed: onFocus,
        icon: const Icon(Icons.play_arrow_rounded),
      ),
    );
  }
}

class _EmptyTasks extends StatelessWidget {
  const _EmptyTasks({required this.hasTodoist, required this.dueToday});
  final bool hasTodoist;
  final bool dueToday;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.task_alt, size: 52),
          const SizedBox(height: 12),
          Text(
            'Nothing waiting here',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 6),
          Text(
            dueToday
                ? 'No tasks have a due date of today. Switch to All active to see everything else.'
                : hasTodoist
                ? 'Sync Todoist or add a local focus task.'
                : 'Add a local task, or connect Todoist in Settings.',
            textAlign: TextAlign.center,
          ),
        ],
      ),
    ),
  );
}

Future<void> showAddTaskDialog(BuildContext context) async {
  final title = TextEditingController();
  final project = TextEditingController(text: 'Local');
  var priority = 1;
  await showDialog<void>(
    context: context,
    builder: (dialogContext) => StatefulBuilder(
      builder: (context, setDialogState) => AlertDialog(
        title: const Text('Add local task'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: title,
                autofocus: true,
                decoration: const InputDecoration(labelText: 'Task'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: project,
                decoration: const InputDecoration(labelText: 'Project'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<int>(
                initialValue: priority,
                decoration: const InputDecoration(labelText: 'Priority'),
                items: [1, 2, 3, 4]
                    .map(
                      (value) => DropdownMenuItem(
                        value: value,
                        child: Text('P${5 - value}'),
                      ),
                    )
                    .toList(),
                onChanged: (value) =>
                    setDialogState(() => priority = value ?? 1),
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
              if (title.text.trim().isEmpty) return;
              await AppScope.of(
                context,
              ).addLocalTask(title.text.trim(), project.text.trim(), priority);
              if (dialogContext.mounted) Navigator.pop(dialogContext);
            },
            child: const Text('Add'),
          ),
        ],
      ),
    ),
  );
  title.dispose();
  project.dispose();
}
