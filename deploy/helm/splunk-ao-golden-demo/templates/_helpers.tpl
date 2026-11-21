{{- define "golden.fullname" -}}
{{- default .Release.Name .Values.nameOverride | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "golden.labels" -}}
app.kubernetes.io/name: splunk-ao-golden-demo
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: splunk-ao-golden-demo
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "golden.selector" -}}
app.kubernetes.io/name: splunk-ao-golden-demo
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "golden.image" -}}
{{- $tag := required "image.tag is required (immutable <version>-<git-sha> tag)" .Values.image.tag -}}
{{- if eq $tag "latest" -}}{{- fail "image.tag must be immutable; do not deploy latest" -}}{{- end -}}
{{ .Values.image.repository }}:{{ $tag }}
{{- end -}}

{{- define "golden.appSecret" -}}{{ default (printf "%s-app" (include "golden.fullname" .)) .Values.app.secretName }}{{- end -}}
{{- define "golden.postgresSecret" -}}{{ default (printf "%s-postgres" (include "golden.fullname" .)) .Values.postgres.secretName }}{{- end -}}
{{- define "golden.tlsSecret" -}}{{ default (printf "%s-tls" (include "golden.fullname" .)) .Values.ingress.tlsSecretName }}{{- end -}}
{{- define "golden.basicAuthSecret" -}}{{ default (printf "%s-basic-auth" (include "golden.fullname" .)) .Values.ingress.basicAuth.secretName }}{{- end -}}

{{/* Volumes shared by the app Pod and the init Job. */}}
{{- define "golden.configVolumes" -}}
- name: app-config
  secret:
    secretName: {{ include "golden.appSecret" . }}
    defaultMode: 0440
- name: tmp
  emptyDir: {}
- name: home
  emptyDir: {}
{{- end -}}

{{- define "golden.configMounts" -}}
- name: app-config
  mountPath: /app/.streamlit/secrets.toml
  subPath: secrets.toml
  readOnly: true
- name: tmp
  mountPath: /tmp
- name: home
  mountPath: /home/app
{{- end -}}
