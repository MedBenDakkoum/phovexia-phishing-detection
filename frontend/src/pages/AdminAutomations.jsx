import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  PlayCircle,
  RefreshCw,
  ShieldCheck,
  Workflow,
  XCircle,
} from "lucide-react";
import { getAdminIntegrations, sendAdminIntegrationTest } from "../api/admin";
import { ApiError } from "../api/errors";
import Button from "../components/ui/Button";
import PageHeader from "../components/ui/PageHeader";
import { EmptyState, ErrorState, Skeleton } from "../components/ui/States";
import { useAsync } from "../hooks/useAsync";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useToast } from "../context/ToastContext";
import { formatDateTime, formatNumber } from "../utils/format";

const WORKFLOWS = [
  {
    id: "W1",
    title: "Alerte phishing confirmé",
    trigger: "Événement scan.confirmed (un analyste confirme un phishing)",
    badge: "Événement de l'application",
    badgeClass: "badge-success",
    description:
      "Déclenché par l'événement scan.confirmed (un analyste confirme un phishing) ; envoie un e-mail d'alerte à l'équipe avec le domaine neutralisé (hxxps://exemple[.]com) et le lien vers le cas.",
  },
  {
    id: "W2",
    title: "Cas à examiner",
    trigger: "Événement scan.needs_review",
    badge: "Événement de l'application",
    badgeClass: "badge-info",
    description:
      "Déclenché par l'événement scan.needs_review ; envoie un e-mail à l'équipe d'analystes pour signaler qu'un cas attend une revue.",
  },
  {
    id: "W3",
    title: "Rapport quotidien",
    trigger: "Planification n8n (Schedule Trigger)",
    badge: "Planification n8n",
    badgeClass: "badge-gold",
    description:
      "Planifié dans n8n ; lit le tableau de bord et la santé du système via l'API et envoie un résumé par e-mail.",
  },
  {
    id: "W4",
    title: "Signalement par formulaire",
    trigger: "Formulaire n8n",
    badge: "Formulaire n8n",
    badgeClass: "badge-info",
    description:
      "Déclenché par un formulaire n8n ; extrait les liens d'un message suspect, les fait analyser par l'API et affiche le verdict.",
  },
];

function statusBanner(data) {
  if (!data.enabled) {
    return {
      className: "status-warning",
      icon: AlertTriangle,
      title: "Intégration désactivée",
      message:
        "N8N_WEBHOOK_BASE_URL est vide : aucun événement n'est émis. Renseignez backend/.env puis recréez le worker Celery.",
    };
  }
  if (!data.reachable) {
    return {
      className: "status-degraded",
      icon: XCircle,
      title: "n8n injoignable",
      message: `L'hôte ${data.host || "configuré"} ne répond pas sur /healthz. Les livraisons échouent après 3 reprises et sont auditées.`,
    };
  }
  return {
    className: "status-ok",
    icon: CheckCircle2,
    title: "Intégration active",
    message: `n8n répond sur ${data.host}. Les événements sont signés (HMAC-SHA256) et livrés par le worker Celery.`,
  };
}

function StatCard({ label, value, hint }) {
  return (
    <article className="card card-pad health-card">
      <div className="health-card-head">
        <span className="health-icon">
          <ShieldCheck size={20} />
        </span>
      </div>
      <h3>{label}</h3>
      <p className="health-message">{value}</p>
      {hint && <p className="muted">{hint}</p>}
    </article>
  );
}

export default function AdminAutomations() {
  useDocumentTitle("Automatisations n8n");
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const { data, error, loading, reload } = useAsync(
    (signal) => getAdminIntegrations(signal),
    []
  );

  const runTest = async () => {
    setBusy(true);
    try {
      const result = await sendAdminIntegrationTest();
      if (result.queued) {
        toast.success("Événement de test mis en file", result.detail);
      } else {
        toast.warning("Aucun événement envoyé", result.detail);
      }
      reload();
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        toast.error(
          "Limite atteinte",
          "5 tests par minute maximum : réessayez dans un instant."
        );
      } else {
        toast.error("Test impossible", err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="card">
        <ErrorState error={error} onRetry={reload} />
      </div>
    );
  }
  if (loading || !data) {
    return (
      <div className="health-grid">
        {[0, 1, 2, 3].map((item) => (
          <div className="card card-pad" key={item}>
            <Skeleton h={18} w="45%" />
            <Skeleton h={12} w="80%" style={{ marginTop: 16 }} />
            <Skeleton h={12} w="60%" style={{ marginTop: 8 }} />
          </div>
        ))}
      </div>
    );
  }

  const banner = statusBanner(data);
  const BannerIcon = banner.icon;
  const events = data.recent_events || [];
  const delivered = data.events_last_24h?.delivered ?? 0;
  const failed = data.events_last_24h?.failed ?? 0;

  return (
    <>
      <PageHeader
        title="Automatisations n8n"
        description="Supervisez l'intégration sortante et déclenchez un événement de test sans quitter l'application."
        actions={
          <div className="toolbar-actions">
            <Button variant="quiet" icon={RefreshCw} onClick={reload} loading={loading}>
              Rafraîchir
            </Button>
            <Button
              variant="gold"
              icon={PlayCircle}
              onClick={runTest}
              loading={busy}
              disabled={!data.enabled}
              title={
                data.enabled
                  ? "Envoyer un événement de test"
                  : "Intégration désactivée : configurez N8N_WEBHOOK_BASE_URL"
              }
            >
              Tester l'intégration
            </Button>
            {data.editor_url && (
              <Button variant="ghost" icon={ExternalLink} href={data.editor_url}>
                Ouvrir n8n
              </Button>
            )}
          </div>
        }
      />

      {!data.enabled && (
        <div className="alert alert-gold" role="status">
          <AlertTriangle size={18} />
          <span>
            Le bouton de test est inactif tant que N8N_WEBHOOK_BASE_URL est vide.
            Aucun secret ni URL webhook complète n'est exposé sur cette page.
          </span>
        </div>
      )}

      <section className={`health-banner ${banner.className}`} aria-live="polite">
        <span className="health-banner-icon">
          <BannerIcon size={28} />
        </span>
        <div>
          <h2>{banner.title}</h2>
          <p>{banner.message}</p>
        </div>
      </section>

      <div className="health-grid">
        <StatCard
          label="Activation"
          value={data.enabled ? "Activée" : "Désactivée"}
          hint="Réglage N8N_WEBHOOK_BASE_URL"
        />
        <StatCard
          label="Hôte du webhook"
          value={data.host || "—"}
          hint="Nom d'hôte uniquement, jamais l'URL complète"
        />
        <StatCard
          label="Livrés (24 h)"
          value={formatNumber(delivered)}
          hint="Entrées d'audit integration.delivered"
        />
        <StatCard
          label="Échecs (24 h)"
          value={formatNumber(failed)}
          hint="Après 3 reprises, avec entrée d'audit"
        />
      </div>

      <section className="card" aria-label="Événements récents">
        <div className="card-head">
          <div>
            <h2 className="card-title">Événements récents</h2>
            <p className="card-sub">
              Les 20 dernières livraisons, issues du journal d'audit immuable.
            </p>
          </div>
        </div>
        {events.length === 0 ? (
          <EmptyState icon={Clock3} title="Aucun événement">
            Les livraisons et les échecs apparaîtront ici dès qu'un événement
            sera émis vers n8n.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="tbl tbl-stack">
              <thead>
                <tr>
                  <th>Événement</th>
                  <th>Statut</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event, index) => (
                  <tr key={`${event.event_type}-${event.occurred_at}-${index}`}>
                    <td data-label="Événement">
                      <strong className="mono">{event.event_type || "—"}</strong>
                    </td>
                    <td data-label="Statut">
                      <span
                        className={`badge ${
                          event.status === "delivered"
                            ? "badge-success"
                            : "badge-danger"
                        }`}
                      >
                        {event.status === "delivered" ? "Livré" : "Échec"}
                      </span>
                    </td>
                    <td data-label="Date" className="muted">
                      {formatDateTime(event.occurred_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-label="Workflows n8n">
        <h2 className="card-title" style={{ marginBottom: 12 }}>
          Workflows attendus dans n8n
        </h2>
        <div className="health-grid">
          {WORKFLOWS.map((workflow) => (
            <article className="card card-pad health-card" key={workflow.id}>
              <div className="health-card-head">
                <span className="health-icon">
                  <Workflow size={20} />
                </span>
                <span className={`badge ${workflow.badgeClass}`}>
                  {workflow.badge}
                </span>
              </div>
              <h3>
                {workflow.id} · {workflow.title}
              </h3>
              <p className="health-message">{workflow.description}</p>
              <dl className="kv health-kv">
                <dt>Déclencheur</dt>
                <dd>{workflow.trigger}</dd>
              </dl>
            </article>
          ))}
        </div>
        <p className="muted" style={{ marginTop: 12 }}>
          n8n n'ouvre jamais les liens : toutes les analyses passent par l'API
          de l'application.
        </p>
      </section>
    </>
  );
}
