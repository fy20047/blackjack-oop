#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Blackjack（21 點）— OOP + MySQL 記錄版
- 單檔可執行
- A 可作 1 或 11（最佳化）
- 莊家 17 停（含 soft 17）
- 下注、Blackjack 3:2
- 顯示回合數、剩餘卡牌數、卡牌不足提示
- Enter=Y 直接下一局
- 以「玩家輸入的名字」作為 Game ID，寫入 MySQL，顯示雲端統計
"""

from __future__ import annotations
import os
import random
import sys
from typing import List, Tuple

# 讀 .env（放在專案根目錄）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import pymysql  # pip install PyMySQL

# ==== 型別定義 ====
Card = Tuple[str, str]
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def clear_screen():
    """嘗試清空終端畫面（跨平台 best-effort）。"""
    import os as _os
    _os.system("cls" if _os.name == "nt" else "clear")


# ==== MySQL 輕量封裝 ====
class DB:
    def __init__(self) -> None:
        self.conn = pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "blackjack"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """建表（無外鍵版本，簡單穩定；之後要可加 FK）。"""
        with self.conn.cursor() as cur:
            # 玩家表：name 唯一，當 Game ID
            cur.execute("""
            CREATE TABLE IF NOT EXISTS players (
              name VARCHAR(64) PRIMARY KEY,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4;
            """)
            # 對局表：用 name 當關聯鍵（不加 FK，PlanetScale 等也 OK）
            cur.execute("""
            CREATE TABLE IF NOT EXISTS rounds (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              name VARCHAR(64) NOT NULL,
              round_no INT NOT NULL,
              bet INT NOT NULL,
              player_hand VARCHAR(128) NOT NULL,
              dealer_hand VARCHAR(128) NOT NULL,
              player_value INT NOT NULL,
              dealer_value INT NOT NULL,
              result VARCHAR(16) NOT NULL,
              chips_after INT NOT NULL,
              deck_remaining INT NOT NULL,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_name_time (name, created_at)
            ) CHARACTER SET utf8mb4;
            """)

    def ensure_player(self, name: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("INSERT IGNORE INTO players(name) VALUES(%s);", (name,))

    def log_round(self, *, name: str, round_no: int, bet: int,
                  player_hand: str, dealer_hand: str,
                  player_value: int, dealer_value: int,
                  result: str, chips_after: int, deck_remaining: int) -> None:
        with self.conn.cursor() as cur:
            cur.execute("""
            INSERT INTO rounds(name, round_no, bet, player_hand, dealer_hand,
                               player_value, dealer_value, result, chips_after, deck_remaining)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);
            """, (name, round_no, bet, player_hand, dealer_hand,
                  player_value, dealer_value, result, chips_after, deck_remaining))

    def get_stats(self, name: str) -> tuple[int, int]:
        """回傳：(歷史總局數, 歷史最高籌碼)"""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) AS cnt, COALESCE(MAX(chips_after), 0) AS mx
                FROM rounds WHERE name=%s;
            """, (name,))
            row = cur.fetchone() or {"cnt": 0, "mx": 0}
            return int(row["cnt"]), int(row["mx"])


# ==== 撲克牌/玩家/遊戲 ====
class Deck:
    def __init__(self, num_decks: int = 1) -> None:
        self.num_decks = num_decks
        self.cards: List[Card] = []
        self._create()
        self.shuffle()

    def _create(self) -> None:
        self.cards = [(r, s) for _ in range(self.num_decks) for s in SUITS for r in RANKS]

    def shuffle(self) -> None:
        random.shuffle(self.cards)

    def draw(self) -> Card:
        if not self.cards:
            # 自動重洗
            self._create()
            self.shuffle()
        return self.cards.pop()


class Player:
    def __init__(self, name: str, chips: int = 100) -> None:
        self.name = name
        self.chips = chips
        self.hand: List[Card] = []

    def reset_hand(self) -> None:
        self.hand.clear()

    def add_card(self, card: Card) -> None:
        self.hand.append(card)

    @property
    def value(self) -> int:
        return hand_value(self.hand)

    def has_blackjack(self) -> bool:
        return len(self.hand) == 2 and self.value == 21


def hand_value(hand: List[Card]) -> int:
    total = 0
    aces = 0
    for r, _ in hand:
        if r in ("J", "Q", "K"):
            total += 10
        elif r == "A":
            total += 11
            aces += 1
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def render_hand(hand: List[Card], hide_first: bool = False) -> str:
    if hide_first and hand:
        shown = ["■"] + [f"{r}{s}" for r, s in hand[1:]]
    else:
        shown = [f"{r}{s}" for r, s in hand]
    return " ".join(shown)


class Game:
    def __init__(self, player_name: str = "Player", num_decks: int = 1, db: DB | None = None) -> None:
        self.deck = Deck(num_decks=num_decks)
        self.player = Player(player_name)
        self.dealer = Player("Dealer", chips=0)
        self.bet = 0
        self.round_no = 0
        self.history: List[str] = []   # 本次執行期間的簡短紀錄
        self.db = db
        if self.db:
            self.db.ensure_player(self.player.name)

        # 卡牌不足提醒門檻（可改）
        self.reshuffle_threshold = 15

    # === 單局流程 ===
    def play_round(self) -> None:
        self.round_no += 1
        self.player.reset_hand()
        self.dealer.reset_hand()
        self.bet = self._ask_bet()

        # 起手發牌
        self.player.add_card(self.deck.draw())
        self.dealer.add_card(self.deck.draw())
        self.player.add_card(self.deck.draw())
        self.dealer.add_card(self.deck.draw())

        # Blackjack 檢查
        if self.player.has_blackjack() or self.dealer.has_blackjack():
            self._show_table(reveal_dealer=True, header="檢查 Blackjack…")
            self._resolve_naturals()
            return

        # 玩家回合
        while True:
            self._show_table(header="你的回合（H=要牌 / S=停牌）")
            choice = self._ask_choice(["H", "S"], prompt="請輸入 H 或 S：")
            if choice == "H":
                self.player.add_card(self.deck.draw())
                if self.player.value > 21:
                    self._show_table(reveal_dealer=True, header="你爆了！")
                    self._player_busts()
                    return
            else:
                break

        # 莊家回合（S17）
        self._show_table(header="莊家回合…")
        while self.dealer.value < 17:
            self.dealer.add_card(self.deck.draw())
            self._show_table(header="莊家要牌…")

        # 結算
        self._show_table(reveal_dealer=True, header="結算…")
        self._settle()

    # === UI & 輸入 ===
    def _show_table(self, reveal_dealer: bool = False, header: str = "") -> None:
        clear_screen()
        if header:
            print(header)
            print("=" * 40)

        remaining_cards = len(self.deck.cards)
        print(f"回合：{self.round_no}    剩餘卡牌數：{remaining_cards}")
        if remaining_cards < self.reshuffle_threshold:
            print("⚠️  剩餘卡牌不足，下回合將自動洗牌！")
        print("-" * 40)

        print(f"莊家: {render_hand(self.dealer.hand, hide_first=not reveal_dealer)}  "
              f"(點數: {'?' if not reveal_dealer else self.dealer.value})")
        print(f"你  : {render_hand(self.player.hand)}  (點數: {self.player.value})")
        print("-" * 40)
        print(f"籌碼：{self.player.chips}    當前下注：{self.bet}")

        # 顯示雲端統計
        if self.db:
            total_rounds, max_chips = self.db.get_stats(self.player.name)
            print(f"雲端統計 → 歷史總局數：{total_rounds}，歷史最高籌碼：{max_chips}")

        # 顯示本次執行的簡短紀錄（最多 5 筆，避免太長）
        if self.history:
            print("\n最近戰績（本次執行）：")
            for rec in self.history[-5:]:
                print("  " + rec)

    def _ask_bet(self) -> int:
        while True:
            try:
                print(f"目前籌碼：{self.player.chips}")
                raw = input("請輸入本局下注（正整數，至少 1）：").strip()
                bet = int(raw)
                if bet < 1:
                    print("下注至少為 1。\n")
                    continue
                if bet > self.player.chips:
                    print("籌碼不足，請重新輸入。\n")
                    continue
                return bet
            except ValueError:
                print("請輸入整數金額。\n")

    def _ask_choice(self, valid: List[str], prompt: str = "請輸入選項：") -> str:
        valid_upper = {v.upper() for v in valid}
        while True:
            ans = input(prompt).strip().upper()
            if ans in valid_upper:
                return ans
            print(f"無效輸入，請輸入 {', '.join(sorted(valid_upper))}。")

    # === 結算 ===
    def _resolve_naturals(self) -> None:
        p_bj = self.player.has_blackjack()
        d_bj = self.dealer.has_blackjack()
        if p_bj and d_bj:
            result = "PUSH"
            print("雙方都是 Blackjack，平局（Push）。")
        elif p_bj:
            result = "PLAYER_BJ"
            win = int(self.bet * 1.5)  # 淨贏 +1.5x
            self.player.chips += win
            print(f"你是 Blackjack！贏得 {win}。")
        else:  # d_bj
            result = "DEALER_BJ"
            self.player.chips -= self.bet
            print("莊家 Blackjack，你輸了。")

        self._persist(result)
        input("按 Enter 繼續…")

    def _player_busts(self) -> None:
        self.player.chips -= self.bet
        print("你輸了。")
        self._persist("PLAYER_BUST")
        input("按 Enter 繼續…")

    def _settle(self) -> None:
        p, d = self.player.value, self.dealer.value
        if d > 21:
            self.player.chips += self.bet
            result = "DEALER_BUST"
            print("莊家爆牌！你贏了。")
        elif p > d:
            self.player.chips += self.bet
            result = "WIN"
            print("你贏了！")
        elif p < d:
            self.player.chips -= self.bet
            result = "LOSE"
            print("你輸了。")
        else:
            result = "PUSH"
            print("平局（Push）。")

        self._persist(result)
        input("按 Enter 繼續…")

    def _persist(self, result: str) -> None:
        """把本局資料寫進 DB，並同步本地歷史。"""
        rec = f"回合 {self.round_no}: {result} → 剩餘籌碼 {self.player.chips}"
        self.history.append(rec)
        if not self.db:
            return
        try:
            self.db.log_round(
                name=self.player.name,
                round_no=self.round_no,
                bet=self.bet,
                player_hand=render_hand(self.player.hand, hide_first=False),
                dealer_hand=render_hand(self.dealer.hand, hide_first=False),
                player_value=self.player.value,
                dealer_value=self.dealer.value,
                result=result,
                chips_after=self.player.chips,
                deck_remaining=len(self.deck.cards),
            )
        except Exception as e:
            print(f"（寫入資料庫失敗：{e}）")


def main() -> None:
    clear_screen()
    print("歡迎來到 Blackjack（21 點）！")
    print("說明：Blackjack 3:2、莊家 17 停、A 可作 1 或 11。")

    name = input("請輸入你的名字（預設 Player）：").strip() or "Player"

    # 嘗試連 DB；失敗就離線本機模式
    db = None
    try:
        db = DB()
        db.ensure_player(name)
        print("（已連線到 MySQL）")
    except Exception as e:
        print(f"（連線 MySQL 失敗，改為僅本機紀錄）原因：{e}")

    game = Game(player_name=name, num_decks=1, db=db)

    while True:
        if game.player.chips <= 0:
            print("你的籌碼用完了，遊戲結束！")
            break
        game.play_round()
        clear_screen()
        print(f"目前籌碼：{game.player.chips}")
        again_raw = input("再來一局嗎？(Enter=Y / N=結束)：").strip().upper()
        again = "Y" if again_raw == "" else again_raw
        if again != "Y":
            break

    print("感謝遊玩！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已離開遊戲。")
        sys.exit(0)
