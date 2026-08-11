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
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _loaded = false;
  bool _showToken = false;
  bool _showPassword = false;
  bool _importLocal = true;

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
    _email.dispose();
    _password.dispose();
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
        _AccountCard(
          email: _email,
          password: _password,
          showPassword: _showPassword,
          importLocal: _importLocal,
          onShowPasswordChanged: () =>
              setState(() => _showPassword = !_showPassword),
          onImportChanged: (value) =>
              setState(() => _importLocal = value ?? false),
        ),
        const SizedBox(height: 14),
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
                const SizedBox(height: 8),
                Text(
                  'For security, Todoist credentials do not cloud-sync. Paste the same token once on each device.',
                  style: Theme.of(context).textTheme.bodySmall,
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
        Card(
          child: Padding(
            padding: EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Local-first by design',
                  style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                Text(
                  controller.cloudSession == null
                      ? 'Tasks, focus history, habits, streaks, moods, and journal entries stay on this device. Todoist only receives requests when you connect it.'
                      : 'Your productivity data stays available offline and syncs when you choose Sync now. Todoist credentials remain encrypted on this device and are never uploaded.',
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 18),
        Center(
          child: Text(
            'ePomodoro Mobile 0.2.3',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ],
    );
  }
}

class _AccountCard extends StatelessWidget {
  const _AccountCard({
    required this.email,
    required this.password,
    required this.showPassword,
    required this.importLocal,
    required this.onShowPasswordChanged,
    required this.onImportChanged,
  });

  final TextEditingController email;
  final TextEditingController password;
  final bool showPassword;
  final bool importLocal;
  final VoidCallback onShowPasswordChanged;
  final ValueChanged<bool?> onImportChanged;

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Account & device sync',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 6),
            if (controller.cloudConfigurationError != null)
              Text(
                controller.cloudConfigurationError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              )
            else if (!controller.cloudAvailable &&
                controller.cloudSession == null)
              const Text(
                'This build is in local-only mode. The app administrator can configure cloud accounts in a future build.',
              )
            else if (controller.cloudSession case final session?) ...[
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const CircleAvatar(child: Icon(Icons.person_outline)),
                title: Text(
                  session.email.isEmpty ? 'Signed-in account' : session.email,
                ),
                subtitle: Text(
                  controller.lastCloudSync == null
                      ? 'Not synced yet'
                      : 'Last synced ${shortDateTime(controller.lastCloudSync!)}',
                ),
              ),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed:
                          controller.cloudSyncing || !controller.cloudAvailable
                          ? null
                          : () => _run(context, controller.syncCloud),
                      icon: const Icon(Icons.sync),
                      label: Text(
                        controller.cloudSyncing ? 'Syncing…' : 'Sync now',
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: controller.cloudSyncing
                          ? null
                          : () => _run(context, controller.signOutCloud),
                      icon: const Icon(Icons.logout),
                      label: const Text('Sign out'),
                    ),
                  ),
                ],
              ),
            ] else ...[
              const Text(
                'Use one account to sync local tasks, focus history, habits, check-ins, moods, and journal entries with desktop. Goals remain preserved in the desktop account profile.',
              ),
              const SizedBox(height: 12),
              TextField(
                controller: email,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Email',
                  prefixIcon: Icon(Icons.email_outlined),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: password,
                obscureText: !showPassword,
                autocorrect: false,
                enableSuggestions: false,
                decoration: InputDecoration(
                  labelText: 'Password',
                  prefixIcon: const Icon(Icons.lock_outline),
                  suffixIcon: IconButton(
                    onPressed: onShowPasswordChanged,
                    icon: Icon(
                      showPassword ? Icons.visibility_off : Icons.visibility,
                    ),
                  ),
                ),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: importLocal,
                onChanged: onImportChanged,
                title: const Text(
                  'Copy this device’s local data into my account',
                ),
                subtitle: const Text(
                  'Recommended when this device already has data. It is merged with cloud data after sign-in.',
                ),
                controlAffinity: ListTileControlAffinity.leading,
              ),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: controller.cloudSyncing
                          ? null
                          : () => _run(
                              context,
                              () => controller.signInCloud(
                                email.text,
                                password.text,
                                importLocal: importLocal,
                              ),
                            ),
                      icon: const Icon(Icons.login),
                      label: const Text('Sign in'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: controller.cloudSyncing
                          ? null
                          : () => _run(
                              context,
                              () => controller.createCloudAccount(
                                email.text,
                                password.text,
                              ),
                            ),
                      child: const Text('Create account'),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _run(
    BuildContext context,
    Future<void> Function() action,
  ) async {
    await action();
    if (context.mounted) {
      final message = AppScope.of(context).message;
      if (message != null) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(message)));
      }
    }
  }
}
