/**
 * Deploy 後の設定不足 (LLM / Trino / CDV 未設定) を UI に伝えるカード。
 *
 * `SetupGuideError` (HTTP 503) をキャッチした場所で表示する。エラーコードごとに
 * 具体的な設定手順を提示し、Project → Settings → Advanced → Environment
 * Variables で env を追加 → Application を再起動する運用を明示する。
 */
import type { SetupGuideError } from "../../api/client";

interface SetupGuideProps {
  error: SetupGuideError;
  /** ✕ でカードを閉じたい場合のコールバック (省略時は close ボタン非表示)。 */
  onDismiss?: () => void;
}

interface GuideDetails {
  title: string;
  envList: Array<{ name: string; hint: string }>;
  extraSteps: string[];
}

/** error_code → 表示用の詳細メタデータ。 */
function guideFor(errorCode: string): GuideDetails {
  switch (errorCode) {
    case "LLM_NOT_CONFIGURED":
      return {
        title: "LLM プロバイダが未設定です",
        envList: [
          {
            name: "SOLOMON_LLM_PROVIDER",
            hint: "cai / anthropic / openai / bedrock のいずれか",
          },
          {
            name: "CAI_INFERENCE_BASE_URL + CAI_INFERENCE_API_KEY",
            hint: "provider=cai の場合",
          },
          {
            name: "ANTHROPIC_API_KEY",
            hint: "provider=anthropic の場合",
          },
          {
            name: "OPENAI_API_KEY",
            hint: "provider=openai の場合",
          },
          {
            name: "AWS_REGION",
            hint: "provider=bedrock の場合 (IAM role 前提)",
          },
        ],
        extraSteps: [
          "Project → Settings → Advanced → Environment Variables に上記を追加",
          "同ページから Application (Solomon) を Restart",
        ],
      };
    case "TRINO_NOT_CONFIGURED":
      return {
        title: "Trino / Tables への接続が未設定、または warehouse が未起動です",
        envList: [
          {
            name: "TRINO_MODE",
            hint: "external (デフォルト) = CDW Trino / internal = warehouse-launcher",
          },
          {
            name: "TRINO_URL / TRINO_HOST",
            hint: "external: CDW coordinator URL（1 行可）/ internal: TRINO_ENDPOINT",
          },
          {
            name: "TRINO_USER / TRINO_PASSWORD",
            hint: "external + Basic 認証時（省略時は Knox JWT）",
          },
        ],
        extraSteps: [
          "internal: Warehouse Launcher Application が status=running になるまで待つ",
          "external: TRINO_MODE=external と TRINO_URL を Project Settings に設定",
          "Tables タブを Refresh、または Application (Solomon) を Restart",
        ],
      };
    case "CDV_NOT_CONFIGURED":
      return {
        title: "Cloudera Data Visualization が未設定です",
        envList: [
          {
            name: "SOLOMON_CDV_BASE_URL",
            hint: "CDV 有効化後に払い出される endpoint URL",
          },
          {
            name: "SOLOMON_CDV_TRINO_CONNECTION_ID",
            hint: "CDV 側の Trino connection ID (省略可)",
          },
        ],
        extraSteps: [
          "Cloudera AI Workbench の Data メニューから CDV を Enable",
          "有効化後に払い出された URL を SOLOMON_CDV_BASE_URL に設定",
          "Project → Settings → Advanced → Environment Variables から Application を Restart",
        ],
      };
    case "S3_ASSUMEROLE_FAILED":
      return {
        title: "S3 資格情報を取得できません",
        envList: [
          {
            name: "SOLOMON_IDBROKER_URL",
            hint: "推奨: Knox → IDBroker → STS（S3 Data Connection 不要）",
          },
          {
            name: "SOLOMON_S3_BUCKETS",
            hint: "Storage タブの実バケット名（カンマ区切り）",
          },
          {
            name: "SOLOMON_AWS_REGION",
            hint: "データレイクのリージョン",
          },
          {
            name: "SOLOMON_S3_CONNECTION_NAME",
            hint: "IDBroker 未使用時のみ: S3 Object Store 等",
          },
        ],
        extraSteps: [
          "Data Connections に S3 が無い環境では SOLOMON_IDBROKER_URL が必須",
          "GET /api/files/diagnostics で idbroker_configured を確認",
          "docs/s3_connectivity.md を参照",
          "Application を Restart",
        ],
      };
    case "GRAPH_NOT_CONFIGURED":
      return {
        title: "PuppyGraph への接続情報が未設定です",
        envList: [
          {
            name: "PUPPYGRAPH_MODE",
            hint: "internal (既定) = endpoints file / external = 外部 PuppyGraph",
          },
          {
            name: "PUPPYGRAPH_URI",
            hint: "Bolt URI (7687)。Iceberg/PostgreSQL catalog と graph schema は PuppyGraph 側",
          },
          {
            name: "PUPPYGRAPH_USERNAME",
            hint: "任意（既定 puppygraph）",
          },
          {
            name: "PUPPYGRAPH_PASSWORD",
            hint: "任意。.solomon/secrets.env 推奨",
          },
        ],
        extraSteps: [
          "internal: puppygraph-launcher が running になるまで待つ",
          ".solomon/puppygraph_endpoints.json を確認（または deploy.env に PUPPYGRAPH_URI）",
          "Solomon Application を Restart",
        ],
      };
    case "OPENSEARCH_NOT_CONFIGURED":
      return {
        title: "Semantic Search (OpenSearch) への接続情報が未設定です",
        envList: [
          {
            name: "OPENSEARCH_MODE",
            hint: "external (デフォルト) = Semantic Search / internal = opensearch-launcher",
          },
          {
            name: "OPENSEARCH_CONNECTION_NAME",
            hint: "external モード: Data Connections の OpenSearch connection 名",
          },
          {
            name: "OPENSEARCH_ENDPOINT",
            hint: "external: クラスタ URL。internal で DNS 不通時は launcher Log の HTTP エンドポイント",
          },
          {
            name: "OPENSEARCH_NAMESPACE",
            hint: "インデックス namespace (default: solomon)",
          },
        ],
        extraSteps: [
          "internal: opensearch-launcher Application が Running か確認し endpoints file を待つ",
          "external: Semantic Search for AWS を Provision し Data Connection を登録",
          "Project → Settings → Advanced → Environment Variables に設定",
          "Solomon Application を Restart",
        ],
      };
    default:
      return {
        title: "セットアップが必要です",
        envList: [],
        extraSteps: [],
      };
  }
}

export function SetupGuide({ error, onDismiss }: SetupGuideProps) {
  const details = guideFor(error.errorCode);
  return (
    <div className="setup-guide" role="alert">
      <div className="setup-guide__head">
        <span className="setup-guide__code">{error.errorCode}</span>
        <h4 className="setup-guide__title">{details.title}</h4>
        {onDismiss && (
          <button
            type="button"
            className="setup-guide__close"
            aria-label="Close"
            onClick={onDismiss}
          >
            ×
          </button>
        )}
      </div>
      <p className="setup-guide__instruction">{error.instruction}</p>
      {details.envList.length > 0 && (
        <>
          <p className="setup-guide__section-label">必要な環境変数</p>
          <ul className="setup-guide__env-list">
            {details.envList.map((e) => (
              <li key={e.name}>
                <code>{e.name}</code>
                <span className="setup-guide__env-hint"> — {e.hint}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {details.extraSteps.length > 0 && (
        <>
          <p className="setup-guide__section-label">手順</p>
          <ol className="setup-guide__steps">
            {details.extraSteps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}
