{{- define "cip.name" -}}
{{- default .Chart.Name .Values.global.projectName | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cip.namespace" -}}
{{- default "city-intersection" .Values.namespace.name -}}
{{- end -}}

{{- define "cip.labels" -}}
app.kubernetes.io/part-of: city-intersection-project
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "cip.selectorLabels" -}}
app.kubernetes.io/part-of: city-intersection-project
{{- end -}}

{{- define "cip.image" -}}
{{- $root := index . 0 -}}
{{- $img := index . 1 -}}
{{- $repository := $img.repository -}}
{{- if $root.Values.global.imageRegistry -}}
{{- $repository = printf "%s/%s" ($root.Values.global.imageRegistry | trimSuffix "/") $img.repository -}}
{{- end -}}
{{- if $img.digest -}}
{{ printf "%s@%s" $repository $img.digest }}
{{- else -}}
{{- $tag := required "image.tag is required when image.digest is not set" $img.tag -}}
{{ printf "%s:%s" $repository $tag }}
{{- end -}}
{{- end -}}

{{- define "cip.replicaCount" -}}
{{- $root := index . 0 -}}
{{- $configured := index . 1 -}}
{{- if $root.Values.global.replicaOverride -}}
{{- $root.Values.global.replicaOverride -}}
{{- else -}}
{{- $configured -}}
{{- end -}}
{{- end -}}

{{- define "cip.serviceAccountName" -}}
{{- if .Values.global.serviceAccount.name -}}
{{- .Values.global.serviceAccount.name | trunc 63 | trimSuffix "-" -}}
{{- else if .Values.global.serviceAccount.create -}}
{{- include "cip.name" . -}}
{{- else -}}
default
{{- end -}}
{{- end -}}

{{- define "cip.podSpecDefaults" -}}
serviceAccountName: {{ include "cip.serviceAccountName" . }}
automountServiceAccountToken: {{ .Values.global.serviceAccount.automountServiceAccountToken | default false }}
enableServiceLinks: {{ .Values.global.enableServiceLinks | default false }}
{{- if .Values.global.imagePullSecrets }}
imagePullSecrets:
  {{- range .Values.global.imagePullSecrets }}
  - name: {{ . }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "cip.podSecurityContext" -}}
{{- if .Values.global.podSecurityContext.enabled }}
runAsNonRoot: {{ .Values.global.security.runAsNonRoot }}
fsGroupChangePolicy: {{ .Values.global.podSecurityContext.fsGroupChangePolicy | default "OnRootMismatch" | quote }}
seccompProfile:
  type: {{ .Values.global.podSecurityContext.seccompProfile.type | default "RuntimeDefault" | quote }}
{{- end }}
{{- end -}}

{{- define "cip.securityContext" -}}
allowPrivilegeEscalation: {{ .Values.global.security.allowPrivilegeEscalation | default false }}
readOnlyRootFilesystem: {{ .Values.global.security.readOnlyRootFilesystem | default false }}
runAsNonRoot: {{ .Values.global.security.runAsNonRoot }}
capabilities:
  drop:
    {{- range .Values.global.security.capabilities.drop }}
    - {{ . | quote }}
    {{- end }}
{{- end -}}

{{- define "cip.topologySpreadConstraints" -}}
{{- $root := index . 0 -}}
{{- $appName := index . 1 -}}
{{- if $root.Values.global.scheduling.topologySpread }}
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      app.kubernetes.io/name: {{ $appName }}
- maxSkew: 1
  topologyKey: kubernetes.io/hostname
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      app.kubernetes.io/name: {{ $appName }}
{{- end }}
{{- end -}}
