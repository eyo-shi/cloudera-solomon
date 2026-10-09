export function WelcomeTab() {
  return (
    <div className="welcome welcome--tab">
      <h2>ようこそ Solomon へ</h2>
      <p>
        左の Explorer からテーブルや S3 オブジェクトを選ぶか、右の Solomon
        に自然言語で指示してください。
      </p>
      <ul className="welcome__hints">
        <li>「s3://demo-bucket/... を取り込んで」</li>
        <li>「そのテーブルのサマリーを作って」</li>
        <li>「ダッシュボードを作って」</li>
      </ul>
    </div>
  );
}
