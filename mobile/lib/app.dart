import 'package:flutter/material.dart';

import 'screens/home_shell.dart';
import 'state/app_controller.dart';

class AppScope extends InheritedNotifier<AppController> {
  const AppScope({
    required AppController controller,
    required super.child,
    super.key,
  }) : super(notifier: controller);

  static AppController of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'AppScope was not found above this context.');
    return scope!.notifier!;
  }
}

class EPomodoroApp extends StatefulWidget {
  const EPomodoroApp({required this.controller, super.key});

  final AppController controller;

  @override
  State<EPomodoroApp> createState() => _EPomodoroAppState();
}

class _EPomodoroAppState extends State<EPomodoroApp>
    with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.detached ||
        state == AppLifecycleState.inactive) {
      widget.controller.checkpointTimer();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final seed = const Color(0xFF7C6FF2);
        return AppScope(
          controller: widget.controller,
          child: MaterialApp(
            title: 'ePomodoro',
            debugShowCheckedModeBanner: false,
            themeMode: widget.controller.darkMode
                ? ThemeMode.dark
                : ThemeMode.light,
            theme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: seed,
                brightness: Brightness.light,
              ),
              useMaterial3: true,
              inputDecorationTheme: const InputDecorationTheme(
                border: OutlineInputBorder(),
              ),
            ),
            darkTheme: ThemeData(
              colorScheme: ColorScheme.fromSeed(
                seedColor: seed,
                brightness: Brightness.dark,
                surface: const Color(0xFF121318),
              ),
              scaffoldBackgroundColor: const Color(0xFF0C0D12),
              cardTheme: const CardThemeData(
                color: Color(0xFF17181F),
                elevation: 0,
              ),
              useMaterial3: true,
              inputDecorationTheme: const InputDecorationTheme(
                filled: true,
                border: OutlineInputBorder(),
              ),
            ),
            home: const HomeShell(),
          ),
        );
      },
    );
  }
}
