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
        title: "Trino / CDW への接続情報が未設定です",
        envList: [
          {
            name: "SOLOMON_TRINO_CONNECTION_NAME",
            hint: "Site Administration → Data Connections で登録した CDW / Trino connection 名",
          },
          {
            name: "SOLOMON_TRINO_HOST / SOLOMON_TRINO_PORT",
            hint: "Data Connections を使わない場合の直接指定 (代替)",
          },
        ],
        extraSteps: [
          "Site Administration → Data Connections で CDW / Trino connection を登録",
          "Project → Settings → Advanced → Environment Variables に上記を設定",
          "同ページから Application を Restart",
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
    case "NEO4J_NOT_CONFIGURED":
      return {
        title: "Neo4j への接続情報が未設定です",
        envList: [
          {
            name: "NEO4J_URI",
            hint: "neo4j-launcher Application Log の Internal / External Bolt URI",
          },
          {
            name: "NEO4J_USERNAME",
            hint: "通常 neo4j",
          },
          {
            name: "NEO4J_PASSWORD",
            hint: "neo4j-launcher Application Log の Password",
          },
          {
            name: "NEO4J_EXTERNAL_URI",
            hint: "Internal DNS が失敗する場合の ELB URI (任意)",
          },
        ],
        extraSteps: [
          "Applications ページで neo4j-launcher が Running であることを確認",
          "Application Log から Bolt URI と Password をコピー",
          "Project → Settings → Advanced → Environment Variables に設定",
          "Solomon Application を Restart",
        ],
      };
    case "OPENSEARCH_NOT_CONFIGURED":
      return {
        title: "Semantic Search (OpenSearch) への接続情報が未設定です",
        envList: [
          {
            name: "SOLOMON_OPENSEARCH_CONNECTION_NAME",
            hint: "Site Administration → Data Connections で登録した OpenSearch connection 名",
          },
          {
            name: "SOLOMON_OPENSEARCH_ENDPOINT",
            hint: "Data Connections を使わない場合のエンドポイント URL",
          },
          {
            name: "SOLOMON_OPENSEARCH_NAMESPACE",
            hint: "インデックス namespace (default: solomon)",
          },
        ],
        extraSteps: [
          "Data Hub で Semantic Search for AWS を Provision",
          "Site Administration → Data Connections で OpenSearch connection を登録",
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
