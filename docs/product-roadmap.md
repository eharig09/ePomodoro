# ePomodoro productivity roadmap

This roadmap builds on the app's existing local-first focus timer, Todoist task
catalog, daily plan, habits, goals, journal, reviews, analytics, optional account
sync, and desktop/mobile clients. Features are ordered by dependency and user
value rather than novelty.

Current delivery status: Phases 1 and 2 are implemented, along with the
calendar-aware portion of Phase 3. Planning data is included in account sync,
while calendar connections and the planning interface currently remain a
desktop/browser experience.

## Product principles

- Help the user make a decision before asking them to enter more data.
- Keep recommendations explainable and easy to override.
- Treat capacity, recovery, and breathing room as part of a good plan.
- Preserve local-first behavior and make every new cloud dependency optional.
- Reuse Todoist labels, task history, habits, goals, and focus history instead of
  creating parallel sources of truth.

## Phase 1: A plan that learns

### Smart daily planning and next-task guidance

- Generate a suggested day from due dates, priority, energy, duration, goals,
  available focus time, and a user-selected buffer.
- Explain why each task was selected and why the next task is recommended.
- Never silently change or complete a Todoist task.
- Let the user edit the suggestion before saving it.

### Planning accuracy

- Compare planned and actual focus duration for completed sessions.
- Learn a conservative adjustment at task, project, and overall levels.
- Require multiple observations before applying a task or project adjustment.
- Show the original estimate, adjusted estimate, evidence level, and sample size.

### Success criteria

- A useful suggested plan can be created in under 30 seconds.
- The suggestion does not exceed the chosen usable capacity.
- Every recommendation contains a plain-language reason.
- Sparse or noisy history falls back safely to the user's configured estimate.

## Phase 2: Start and finish the day deliberately

### Daily startup

- Review carried tasks and today's habits.
- Confirm energy, focus capacity, shutdown time, and one daily intention.
- Choose no more than three essential outcomes.

### Daily shutdown

- Review completed work and actual focus time.
- Resolve each unfinished planned task: continue, defer, or remove.
- Record wins, blockers, and tomorrow's first task.
- Save completion state before the page closes or refreshes.

### Weekly planning and review

- Combine the existing weekly evidence review with next-week objectives.
- Carry an objective forward without copying all of its tasks.
- Surface estimate drift, project imbalance, habit adherence, and energy patterns.

## Phase 3: Protect time and attention

### Calendar-aware time blocking

- Implemented: read-only Google, Outlook, and standard ICS availability.
- Implemented: place estimated tasks into open windows without altering the calendar.
- Add optional write-back only after the user explicitly enables it.

### Interruption capture and focus guardrails

- Add one-tap interruption categories and a quick note during focus.
- Keep interruption capture from pausing or ending the timer.
- Add optional desktop notification silencing and website/app blocking later.

## Phase 4: Flexible routines and capture

### Flexible habit windows

- Support targets such as three times per week or preferred time windows.
- Reschedule a missed opportunity without breaking a valid frequency streak.

### Universal inbox

- Capture a thought from any desktop page or Android share action.
- Process each item into a task, habit, goal, journal entry, or deletion.

## Phase 5: Direction, resilience, and trust

### Project and goal time budgets

- Compare intended and actual weekly focus allocation.
- Warn when lower-value work crowds out protected goals.

### Backup and restore enhancements

- Build on the existing health screen, automatic backups, JSON export, and
  restore points.
- Add documented CSV exports alongside the complete JSON archive.
- Preview a restore and create a safety backup before applying it.

## Delivery order

1. Estimation calibration and smart plan generation.
2. Daily startup and shutdown persistence.
3. Weekly planning improvements and cross-device sync for planning data.
4. Calendar availability and time blocking. (Delivered.)
5. Interruption capture and optional focus guardrails.
6. Flexible habit windows and universal inbox.
7. Time budgets and full backup/restore UI.
