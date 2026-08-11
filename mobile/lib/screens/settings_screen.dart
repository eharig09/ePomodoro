import 'package:flutter/material.dart';

import '../app.dart';
import '../models.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _token = TextEditingController();
  bool _loaded = false;
  bool _showToken = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_loaded) {
      _loaded = true;
      AppScope.of(context).readTodoistToken().then((value) {
        if (mounted) setState(() => _token.text = value);
      });
    }
  }

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 18, 16, 32),
      children: [
        const Text(
          'Settings',
          style: TextStyle(fontSize: 30, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 18),
        Card(
          child: Column(
            children: [
              SwitchListTile(
                title: const Text('Dark mode'),
                subtitle: const Text('Uses the calm dark theme by default.'),
                value: controller.darkMode,
                onChanged: controller.setDarkMode,
              ),
              const Divider(height: 1),
              SwitchListTile(
                title: const Text('Completion chime'),
                subtitle: const Text(
                  'A gentle three-second chime at the end of a timer.',
                ),
                value: controller.chimeEnabled,
                onChanged: controller.setChimeEnabled,
              ),
              if (controller.chimeEnabled)
                Align(
                  alignment: Alignment.centerRight,
                  child: Padding(
                    padding: const EdgeInsets.only(right: 12, bottom: 8),
                    child: TextButton.icon(
                      onPressed: controller.chime.play,
                      icon: const Icon(Icons.volume_up_outlined),
                      label: const Text('Preview'),
                    ),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Todoist · optional',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 4),
                const Text(
                  'Paste a personal API token to import active tasks, complete them, and recognize habit completions from the previous 45 days.',
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _token,
                  obscureText: !_showToken,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: InputDecoration(
                    labelText: 'Todoist API token',
                    prefixIcon: const Icon(Icons.key_outlined),
                    suffixIcon: IconButton(
                      onPressed: () => setState(() => _showToken = !_showToken),
                      icon: Icon(
                        _showToken ? Icons.visibility_off : Icons.visibility,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'Stored in Android’s encrypted credential storage, separately from the productivity database.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.tonal(
                        onPressed: () async {
                          await controller.saveTodoistToken(_token.text);
                          if (context.mounted && controller.message != null) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(controller.message!)),
                            );
                          }
                        },
                        child: Text(
                          _token.text.trim().isEmpty
                              ? 'Use local mode'
                              : 'Save token',
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: controller.syncing
                            ? null
                            : () async {
                                await controller.saveTodoistToken(_token.text);
                                await controller.syncTodoist();
                                if (context.mounted &&
                                    controller.message != null) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                      content: Text(controller.message!),
                                    ),
                                  );
                                }
                              },
                        icon: const Icon(Icons.sync),
                        label: Text(
                          controller.syncing ? 'Syncing…' : 'Save & sync',
                        ),
                      ),
                    ),
                  ],
                ),
                if (controller.lastSync != null) ...[
                  const SizedBox(height: 10),
                  Text('Last synced ${shortDateTime(controller.lastSync!)}'),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 14),
        const Card(
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Local-first by design',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
                SizedBox(height: 6),
                Text(
                  'Tasks, focus history, habits, streaks, moods, and journal entries stay on this device. Todoist only receives requests when you connect it and choose to sync or complete a Todoist task.',
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 18),
        Center(
          child: Text(
            'ePomodoro Mobile 0.1.0',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }
}
