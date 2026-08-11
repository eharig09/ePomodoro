import 'package:flutter/material.dart';

import '../app.dart';
import '../models.dart';
import 'focus_screen.dart';
import 'habits_screen.dart';
import 'history_screen.dart';
import 'settings_screen.dart';
import 'today_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  void _focusTask(TaskItem task) {
    AppScope.of(context).configureTimer(task: task, isBreak: false);
    setState(() => _index = 1);
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    if (controller.loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    final pages = [
      TodayScreen(onFocusTask: _focusTask),
      const FocusScreen(),
      const HabitsScreen(),
      const HistoryScreen(),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: SafeArea(
        child: IndexedStack(index: _index, children: pages),
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (value) => setState(() => _index = value),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.today_outlined),
            label: 'Today',
          ),
          NavigationDestination(
            icon: Icon(Icons.timer_outlined),
            label: 'Focus',
          ),
          NavigationDestination(
            icon: Icon(Icons.checklist_rounded),
            label: 'Habits',
          ),
          NavigationDestination(icon: Icon(Icons.history), label: 'History'),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            label: 'Settings',
          ),
        ],
      ),
    );
  }
}
