import 'package:flutter/material.dart';

import '../app.dart';
import '../models.dart';

class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final focusedMinutes = controller.sessions.fold<int>(
      0,
      (total, session) => total + (session.actualSeconds / 60).round(),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'History',
                style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700),
              ),
              Text(
                '${controller.sessions.length} sessions · $focusedMinutes focused minutes',
              ),
            ],
          ),
        ),
        Expanded(
          child: controller.sessions.isEmpty
              ? const Center(
                  child: Text('Completed focus blocks will appear here.'),
                )
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 28),
                  itemCount: controller.sessions.length,
                  itemBuilder: (context, index) {
                    final session = controller.sessions[index];
                    return Card(
                      child: ListTile(
                        leading: CircleAvatar(
                          child: Text(
                            '${(session.actualSeconds / 60).round()}',
                          ),
                        ),
                        title: Text(session.taskName),
                        subtitle: Text(
                          '${session.projectName} · ${shortDateTime(session.startedAt)}\n'
                          '${_statusLabel(session.status)}${session.notes.isEmpty ? '' : ' · ${session.notes}'}',
                        ),
                        isThreeLine: true,
                        trailing: IconButton(
                          tooltip: 'Edit history',
                          onPressed: () => _editSession(context, session),
                          icon: const Icon(Icons.edit_outlined),
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  String _statusLabel(String status) => switch (status) {
    'completed' => 'Completed',
    'continue' => 'Continue',
    'interrupted' => 'Interrupted',
    'abandoned' => 'Abandoned',
    _ => status,
  };

  Future<void> _editSession(BuildContext context, FocusSession session) async {
    final notes = TextEditingController(text: session.notes);
    var status = session.status;
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: const Text('Edit focus history'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                initialValue: status,
                decoration: const InputDecoration(labelText: 'Outcome'),
                items:
                    const {
                          'completed': 'Completed',
                          'continue': 'Continue',
                          'interrupted': 'Interrupted',
                          'abandoned': 'Abandoned',
                        }.entries
                        .map(
                          (entry) => DropdownMenuItem(
                            value: entry.key,
                            child: Text(entry.value),
                          ),
                        )
                        .toList(),
                onChanged: (value) =>
                    setDialogState(() => status = value ?? status),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: notes,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Notes'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () async {
                final confirmed = await showDialog<bool>(
                  context: dialogContext,
                  builder: (confirmContext) => AlertDialog(
                    title: const Text('Delete this session?'),
                    content: const Text(
                      'Use this for tests or time that should not count.',
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(confirmContext, false),
                        child: const Text('Cancel'),
                      ),
                      FilledButton(
                        onPressed: () => Navigator.pop(confirmContext, true),
                        child: const Text('Delete'),
                      ),
                    ],
                  ),
                );
                if (confirmed == true && dialogContext.mounted) {
                  await AppScope.of(context).deleteSession(session.id);
                  if (dialogContext.mounted) Navigator.pop(dialogContext);
                }
              },
              child: const Text('Delete'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () async {
                await AppScope.of(context).updateSession(
                  session.copyWith(status: status, notes: notes.text.trim()),
                );
                if (dialogContext.mounted) Navigator.pop(dialogContext);
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    notes.dispose();
  }
}
