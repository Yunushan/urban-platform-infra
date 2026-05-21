{{- define "cip.name" -}}
{{- default .Chart.Name .Values.global.projectName | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "cip.namespace" -}}
{{- default "urban-platform" .Values.namespace.name -}}
{{- end -}}

{{- define "cip.labels" -}}
app.kubernetes.io/part-of: urban-platform-infra
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "cip.selectorLabels" -}}
app.kubernetes.io/part-of: urban-platform-infra
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

{{- define "cip.storageClassName" -}}
{{- $root := index . 0 -}}
{{- $explicit := index . 1 | default "" -}}
{{- $tierName := index . 2 | default "hot" -}}
{{- if $explicit -}}
{{- $explicit -}}
{{- else -}}
{{- $tiers := $root.Values.storageTiers | default dict -}}
{{- $tier := get $tiers $tierName | default dict -}}
{{- if and ($tier.enabled | default false) $tier.storageClassName -}}
{{- $tier.storageClassName -}}
{{- end -}}
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

{{- define "cip.ingressAnnotations" -}}
{{- $className := .Values.ingress.className | default "traefik" -}}
{{- if eq $className "nginx" }}
nginx.ingress.kubernetes.io/proxy-body-size: "50m"
nginx.ingress.kubernetes.io/ssl-redirect: {{ .Values.ingress.sslRedirect | default true | quote }}
nginx.ingress.kubernetes.io/force-ssl-redirect: {{ .Values.ingress.forceSslRedirect | default true | quote }}
{{- else if eq $className "traefik" }}
traefik.ingress.kubernetes.io/router.entrypoints: "websecure"
{{- if .Values.ingress.tls.enabled }}
traefik.ingress.kubernetes.io/router.tls: "true"
{{- end }}
{{- $middlewares := include "cip.traefikWebsecureMiddlewares" . -}}
{{- if $middlewares }}
traefik.ingress.kubernetes.io/router.middlewares: {{ $middlewares | quote }}
{{- end }}
{{- end }}
{{- with .Values.ingress.annotations }}
{{- toYaml . }}
{{- end }}
{{- end -}}

{{- define "cip.ingressHost" -}}
{{- .Values.ingress.host | default .Values.global.cluster.domain -}}
{{- end -}}

{{- define "cip.ingressTlsSecretName" -}}
{{- .Values.ingress.tls.secretName | default "urban-platform-tls" -}}
{{- end -}}

{{- define "cip.traefikRedirectMiddlewareRef" -}}
{{- printf "%s-redirect-https@kubernetescrd" (include "cip.namespace" .) -}}
{{- end -}}

{{- define "cip.traefikSourceAllowListMiddlewareName" -}}
{{- "source-allow-list" -}}
{{- end -}}

{{- define "cip.traefikSourceAllowListMiddlewareRef" -}}
{{- printf "%s-%s@kubernetescrd" (include "cip.namespace" .) (include "cip.traefikSourceAllowListMiddlewareName" .) -}}
{{- end -}}

{{- define "cip.ingressSourceAllowListCidrs" -}}
{{- $allowList := .Values.ingress.sourceAllowList | default dict -}}
{{- $cidrs := list -}}
{{- range ($allowList.cidrs | default list) -}}
{{- $cidrs = append $cidrs . -}}
{{- end -}}
{{- $cidrsText := $allowList.cidrsText | default "" -}}
{{- if $cidrsText -}}
{{- range (splitList " " $cidrsText) -}}
{{- if . -}}
{{- $cidrs = append $cidrs . -}}
{{- end -}}
{{- end -}}
{{- end -}}
{{- join "," $cidrs -}}
{{- end -}}

{{- define "cip.traefikAllowListEnabled" -}}
{{- $allowList := .Values.ingress.sourceAllowList | default dict -}}
{{- $cidrsCsv := include "cip.ingressSourceAllowListCidrs" . -}}
{{- if and ($allowList.enabled | default false) $cidrsCsv -}}true{{- end -}}
{{- end -}}

{{- define "cip.traefikWebsecureMiddlewares" -}}
{{- if include "cip.traefikAllowListEnabled" . -}}
{{- include "cip.traefikSourceAllowListMiddlewareRef" . -}}
{{- end -}}
{{- end -}}

{{- define "cip.traefikWebMiddlewares" -}}
{{- $middlewares := list (include "cip.traefikRedirectMiddlewareRef" .) -}}
{{- if include "cip.traefikAllowListEnabled" . -}}
{{- $middlewares = prepend $middlewares (include "cip.traefikSourceAllowListMiddlewareRef" .) -}}
{{- end -}}
{{- join "," $middlewares -}}
{{- end -}}

{{- define "cip.traefikHttpRedirectAnnotations" -}}
traefik.ingress.kubernetes.io/router.entrypoints: "web"
traefik.ingress.kubernetes.io/router.middlewares: {{ include "cip.traefikWebMiddlewares" . | quote }}
{{- with .Values.ingress.annotations }}
{{- toYaml . }}
{{- end }}
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
