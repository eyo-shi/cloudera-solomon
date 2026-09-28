/**
 * グローバルヘッダー: Cloudera ロゴ。
 */
export function AppHeader() {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <img
          src="/cldr_corp_logo_color_rgb_101.svg"
          alt="Cloudera"
          className="app-header__logo"
          width={148}
          height={18}
        />
      </div>
    </header>
  );
}
