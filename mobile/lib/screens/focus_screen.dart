import 'package:flutter/material.dart';

import '../app.dart';
import '../state/app_controller.dart';
import 'today_screen.dart';

class FocusScreen extends StatelessWidget {
  const FocusScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final total = controller.timerMinutes * 60;
    final progress = total == 0 ? 0.0 : controller.remainingSeconds / total;
    final minutes = controller.remainingSeconds ~/ 60;
    final seconds = controller.remainingSeconds % 60;
    final presets = controller.timerIsBreak ? [5, 10, 15] : [15, 25, 50];

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 32),
      children: [
        Text(
          controller.timerIsBreak ? 'Break' : 'Focus',
          style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        Text(
          controller.timerRunning
              ? 'Stay with this one thing.'
              : 'Choose a task, or use Generic focus with no linked task.',
        ),
        const SizedBox(height: 20),
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(
              value: false,
              icon: Icon(Icons.bolt),
              label: Text('Focus'),
            ),
            ButtonSegment(
              value: true,
              icon: Icon(Icons.coffee),
              label: Text('Break'),
            ),
          ],
          selected: {controller.timerIsBreak},
          onSelectionChanged: controller.timerRunning
              ? null
              : (value) {
                  final isBreak = value.first;
                  controller.configureTimer(
                    isBreak: isBreak,
                    minutes: isBreak ? 5 : 25,
                  );
                },
        ),
        if (!controller.timerIsBreak) ...[
          const SizedBox(height: 16),
          DropdownButtonFormField<String>(
            initialValue:
                controller.timerTask?.id == AppController.genericFocusTask.id
                ? AppController.genericFocusTask.id
                : controller.timerTask != null &&
                      controller.tasks.any(
                        (task) => task.id == controller.timerTask!.id,
                      )
                ? controller.timerTask!.id
                : null,
            decoration: const InputDecoration(
              labelText: 'Focus task',
              prefixIcon: Icon(Icons.task_alt),
            ),
            items: [
              const DropdownMenuItem(
                value: 'generic:focus',
                child: Text('Generic focus · no linked task'),
              ),
              ...controller.tasks.map(
                (task) => DropdownMenuItem(
                  value: task.id,
                  child: Text(task.title, overflow: TextOverflow.ellipsis),
                ),
              ),
            ],
            onChanged: controller.timerRunning
                ? null
                : (id) {
                    if (id == AppController.genericFocusTask.id) {
                      controller.configureTimer(generic: true);
                      return;
                    }
                    final task = controller.tasks
                        .where((task) => task.id == id)
                        .firstOrNull;
                    controller.configureTimer(task: task);
                  },
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: controller.timerRunning
                  ? null
                  : () => showAddTaskDialog(context),
              icon: const Icon(Icons.add),
              label: const Text('Add local task'),
            ),
          ),
        ],
        const SizedBox(height: 20),
        Center(
          child: SizedBox.square(
            dimension: 230,
            child: Stack(
              alignment: Alignment.center,
              children: [
                SizedBox.expand(
                  child: CircularProgressIndicator(
                    value: progress,
                    strokeWidth: 11,
                    strokeCap: StrokeCap.round,
                    backgroundColor: Theme.of(
                      context,
                    ).colorScheme.surfaceContainerHighest,
                  ),
                ),
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      '$minutes:${seconds.toString().padLeft(2, '0')}',
                      style: const TextStyle(
                        fontSize: 52,
                        fontWeight: FontWeight.w700,
                        fontFeatures: [FontFeature.tabularFigures()],
                      ),
                    ),
                    Text(controller.timerRunning ? 'RUNNING' : 'READY'),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 20),
        Wrap(
          alignment: WrapAlignment.center,
          spacing: 8,
          children: [
            for (final value in presets)
              ChoiceChip(
                label: Text('$value min'),
                selected: controller.timerMinutes == value,
                onSelected: controller.timerRunning
                    ? null
                    : (_) => controller.configureTimer(minutes: value),
              ),
            ActionChip(
              avatar: const Icon(Icons.tune, size: 18),
              label: const Text('Custom'),
              onPressed: controller.timerRunning
                  ? null
                  : () => _showCustomDuration(context),
            ),
          ],
        ),
        const SizedBox(height: 22),
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(52),
                ),
                onPressed: controller.timerRunning
                    ? controller.pauseTimer
                    : controller.startTimer,
                icon: Icon(
                  controller.timerRunning ? Icons.pause : Icons.play_arrow,
                ),
                label: Text(controller.timerRunning ? 'Pause' : 'Start'),
              ),
            ),
            if (controller.timerStartedAt != null) ...[
              const SizedBox(width: 10),
              OutlinedButton(
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(56, 52),
                ),
                onPressed: () => _finishDialog(context),
                child: const Icon(Icons.stop_rounded),
              ),
            ],
          ],
        ),
        if (!controller.timerIsBreak) ...[
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                children: [
                  const Icon(Icons.save_outlined),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Active time is checkpointed every five seconds, so closing the app will not erase the session.',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }

  Future<void> _showCustomDuration(BuildContext context) async {
    final controller = AppScope.of(context);
    final input = TextEditingController(text: '${controller.timerMinutes}');
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Custom timer'),
        content: TextField(
          controller: input,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(labelText: 'Minutes'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final value = int.tryParse(input.text);
              if (value == null || value < 1 || value > 240) return;
              controller.configureTimer(minutes: value);
              Navigator.pop(dialogContext);
            },
            child: const Text('Set'),
          ),
        ],
      ),
    );
    input.dispose();
  }

  Future<void> _finishDialog(BuildContext context) async {
    final controller = AppScope.of(context);
    if (controller.timerIsBreak) {
      await controller.finishTimer('completed');
      return;
    }
    final notes = TextEditingController();
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.fromLTRB(
          20,
          20,
          20,
          MediaQuery.viewInsetsOf(sheetContext).bottom + 20,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Save this focus block',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: notes,
              decoration: const InputDecoration(labelText: 'Notes (optional)'),
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final entry in const {
                  'completed': 'Completed',
                  'continue': 'Continue',
                  'interrupted': 'Interrupted',
                  'abandoned': 'Abandoned',
                }.entries)
                  FilledButton.tonal(
                    onPressed: () async {
                      await controller.finishTimer(
                        entry.key,
                        notes: notes.text,
                      );
                      if (sheetContext.mounted) Navigator.pop(sheetContext);
                    },
                    child: Text(entry.value),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
    notes.dispose();
  }
}
