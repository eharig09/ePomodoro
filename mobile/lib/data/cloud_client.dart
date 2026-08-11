import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

class CloudException implements Exception {
  const CloudException(this.message);

  final String message;

  @override
  String toString() => message;
}

class CloudConfig {
  const CloudConfig({required this.url, required this.publishableKey});

  static const configuredUrl = String.fromEnvironment('SUPABASE_URL');
  static const configuredKey = String.fromEnvironment(
    'SUPABASE_PUBLISHABLE_KEY',
  );

  final String url;
  final String publishableKey;

  static CloudConfig? fromEnvironment() {
    final url = configuredUrl.trim().replaceFirst(RegExp(r'/$'), '');
    final key = configuredKey.trim();
    if (url.isEmpty && key.isEmpty) return null;
    return validate(url, key);
  }

  static CloudConfig validate(String rawUrl, String rawKey) {
    final url = rawUrl.trim().replaceFirst(RegExp(r'/$'), '');
    final key = rawKey.trim();
    if (url.isEmpty || key.isEmpty) {
      throw const CloudException(
        'Cloud sync needs both its URL and publishable key.',
      );
    }
    final uri = Uri.tryParse(url);
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
      throw const CloudException('Cloud sync URL must use HTTPS.');
    }
    if (_isPrivilegedKey(key)) {
      throw const CloudException(
        'A service-role key must never be included in the app.',
      );
    }
    return CloudConfig(url: url, publishableKey: key);
  }

  static bool _isPrivilegedKey(String key) {
    if (key.toLowerCase().contains('service_role')) return true;
    final parts = key.split('.');
    if (parts.length != 3) return false;
    try {
      final claims = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(parts[1]))),
      );
      return claims is Map && claims['role'] == 'service_role';
    } catch (_) {
      return false;
    }
  }
}

class CloudSession {
  const CloudSession({
    required this.accessToken,
    required this.refreshToken,
    required this.userId,
    required this.email,
    required this.expiresAt,
  });

  final String accessToken;
  final String refreshToken;
  final String userId;
  final String email;
  final DateTime expiresAt;

  bool get expiresSoon => expiresAt.isBefore(
    DateTime.now().toUtc().add(const Duration(minutes: 2)),
  );

  Map<String, Object?> toJson() => {
    'access_token': accessToken,
    'refresh_token': refreshToken,
    'user_id': userId,
    'email': email,
    'expires_at': expiresAt.toUtc().toIso8601String(),
  };

  static CloudSession? fromJson(Object? value) {
    if (value is! Map) return null;
    final expiresAt = DateTime.tryParse(value['expires_at']?.toString() ?? '');
    final userId = value['user_id']?.toString() ?? '';
    final accessToken = value['access_token']?.toString() ?? '';
    final refreshToken = value['refresh_token']?.toString() ?? '';
    if (expiresAt == null ||
        userId.isEmpty ||
        accessToken.isEmpty ||
        refreshToken.isEmpty) {
      return null;
    }
    return CloudSession(
      accessToken: accessToken,
      refreshToken: refreshToken,
      userId: userId,
      email: value['email']?.toString() ?? '',
      expiresAt: expiresAt.toUtc(),
    );
  }
}

class CloudClient {
  CloudClient({
    required this.storage,
    CloudConfig? config,
    http.Client? httpClient,
  }) : config = config ?? CloudConfig.fromEnvironment(),
       httpClient = httpClient ?? http.Client();

  static const _sessionKey = 'epomodoro_cloud_session';

  final FlutterSecureStorage storage;
  final CloudConfig? config;
  final http.Client httpClient;

  bool get available => config != null;

  Future<CloudSession?> restoreSession() async {
    final raw = await storage.read(key: _sessionKey);
    if (raw == null) return null;
    try {
      return CloudSession.fromJson(jsonDecode(raw));
    } catch (_) {
      await storage.delete(key: _sessionKey);
      return null;
    }
  }

  Future<CloudSession?> signUp(String email, String password) async {
    _validateCredentials(email, password);
    final result = await _request(
      'POST',
      '/auth/v1/signup',
      body: {'email': email.trim().toLowerCase(), 'password': password},
    );
    final session = _sessionFromResponse(result);
    if (session != null) await _saveSession(session);
    return session;
  }

  Future<CloudSession> signIn(String email, String password) async {
    _validateCredentials(email, password);
    final result = await _request(
      'POST',
      '/auth/v1/token?grant_type=password',
      body: {'email': email.trim().toLowerCase(), 'password': password},
    );
    final session = _sessionFromResponse(result);
    if (session == null) {
      throw const CloudException('The account did not return a user session.');
    }
    await _saveSession(session);
    return session;
  }

  Future<void> signOut() => storage.delete(key: _sessionKey);

  Future<void> mergeRecords(List<Map<String, Object?>> records) async {
    if (records.isEmpty) return;
    await authorizedRequest(
      'POST',
      '/rest/v1/rpc/merge_sync_records',
      body: {'p_records': records},
    );
  }

  Future<List<Map<String, Object?>>> fetchRecords() async {
    final records = <Map<String, Object?>>[];
    const pageSize = 1000;
    var offset = 0;
    while (true) {
      final query = Uri(
        queryParameters: {
          'select':
              'entity_type,entity_id,payload,client_updated_at,device_id,deleted_at,server_updated_at',
          'order': 'server_updated_at.asc,entity_type.asc,entity_id.asc',
          'limit': '$pageSize',
          'offset': '$offset',
        },
      ).query;
      final result = await authorizedRequest(
        'GET',
        '/rest/v1/sync_records?$query',
      );
      if (result is! List) {
        throw const CloudException('Cloud sync returned invalid data.');
      }
      final page = result
          .whereType<Map>()
          .map((item) => item.map((key, value) => MapEntry('$key', value)))
          .toList();
      records.addAll(page);
      if (page.length < pageSize) return records;
      offset += pageSize;
    }
  }

  Future<Object?> authorizedRequest(
    String method,
    String path, {
    Object? body,
  }) async {
    var session = await restoreSession();
    if (session == null) throw const CloudException('Sign in before syncing.');
    if (session.expiresSoon) session = await _refresh(session);
    var response = await _send(method, path, body: body, session: session);
    if (response.statusCode == 401) {
      session = await _refresh(session);
      response = await _send(method, path, body: body, session: session);
    }
    return _decodeSuccessful(response);
  }

  Future<CloudSession> _refresh(CloudSession session) async {
    final result = await _request(
      'POST',
      '/auth/v1/token?grant_type=refresh_token',
      body: {'refresh_token': session.refreshToken},
    );
    final refreshed = _sessionFromResponse(result);
    if (refreshed == null) {
      throw const CloudException(
        'Your account session could not be refreshed.',
      );
    }
    await _saveSession(refreshed);
    return refreshed;
  }

  Future<Object?> _request(String method, String path, {Object? body}) async {
    final response = await _send(method, path, body: body);
    return _decodeSuccessful(response);
  }

  Future<http.Response> _send(
    String method,
    String path, {
    Object? body,
    CloudSession? session,
  }) async {
    final activeConfig = config;
    if (activeConfig == null) {
      throw const CloudException('Cloud accounts are not configured.');
    }
    final headers = <String, String>{
      'apikey': activeConfig.publishableKey,
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      if (session != null) 'Authorization': 'Bearer ${session.accessToken}',
    };
    final request = http.Request(method, Uri.parse('${activeConfig.url}$path'))
      ..headers.addAll(headers);
    if (body != null) request.body = jsonEncode(body);
    try {
      final streamed = await httpClient
          .send(request)
          .timeout(const Duration(seconds: 30));
      return http.Response.fromStream(streamed);
    } catch (_) {
      throw const CloudException(
        'Could not reach cloud sync. Your local data is safe.',
      );
    }
  }

  Object? _decodeSuccessful(http.Response response) {
    Object? parsed;
    if (response.body.isNotEmpty) {
      try {
        parsed = jsonDecode(response.body);
      } catch (_) {
        parsed = response.body;
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      var message = 'Cloud request failed (${response.statusCode}).';
      if (parsed is Map) {
        for (final key in ['msg', 'message', 'error_description', 'error']) {
          final candidate = parsed[key]?.toString().trim() ?? '';
          if (candidate.isNotEmpty) {
            message = candidate;
            break;
          }
        }
      }
      throw CloudException(message);
    }
    return parsed;
  }

  CloudSession? _sessionFromResponse(Object? value) {
    if (value is! Map || value['access_token'] == null) return null;
    final user = value['user'];
    if (user is! Map || user['id'] == null) return null;
    final expiresIn = int.tryParse('${value['expires_in'] ?? 3600}') ?? 3600;
    return CloudSession(
      accessToken: '${value['access_token']}',
      refreshToken: '${value['refresh_token']}',
      userId: '${user['id']}',
      email: '${user['email'] ?? ''}',
      expiresAt: DateTime.now().toUtc().add(Duration(seconds: expiresIn)),
    );
  }

  Future<void> _saveSession(CloudSession session) =>
      storage.write(key: _sessionKey, value: jsonEncode(session.toJson()));

  void _validateCredentials(String email, String password) {
    if (!email.trim().contains('@')) {
      throw const CloudException('Enter a valid email address.');
    }
    if (password.length < 8) {
      throw const CloudException('Use a password with at least 8 characters.');
    }
  }
}
