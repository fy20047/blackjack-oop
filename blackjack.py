#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
終端版 Blackjack（21 點）— 可直接執行的單檔專案

特色：
- 單一檔案即可執行，無需任何外部套件
- OOP 架構（Deck, Player, Game）
- 正確的 A（Ace）計分邏輯（1 或 11，取最優）
- 莊家規則：17 停（含 soft 17）
- 支援下注、Blackjack 3:2 賠率、平局 Push
- 介面清楚，內含錯誤輸入防護

執行：
    python blackjack.py

作者提示：若要做成課堂小專案，可把此檔命名為 blackjack.py，並附上 README 與流程圖即可。
"""
from __future__ import annotations
import random
import sys
from typing import List, Tuple

# 型別別名：牌用 (value, suit) 表示，例如 ("A", "♠")
Card = Tuple[str, str]

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def clear_screen():
    """嘗試清空終端畫面（跨平台 best-effort）。"""
    import os
    os.system("cls" if os.name == "nt" else "clear")


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
    """計算手牌最佳點數（A 可為 11 或 1）。Greedy：先當 11，爆了再把 A 當 1。"""
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
    """把手牌轉成漂亮的字串；hide_first=True 會把第一張蓋牌顯示為 ■"""
    if hide_first and hand:
        shown = ["■"] + [f"{r}{s}" for r, s in hand[1:]]
    else:
        shown = [f"{r}{s}" for r, s in hand]
    return " ".join(shown)


class Game:
    def __init__(self, player_name: str = "Player", num_decks: int = 1) -> None:
        self.deck = Deck(num_decks=num_decks)
        self.player = Player(player_name)
        self.dealer = Player("Dealer", chips=0)
        self.bet = 0

    # === 單局流程 ===
    def play_round(self) -> None:
        self.player.reset_hand()
        self.dealer.reset_hand()
        self.bet = self._ask_bet()

        # 發初始牌
        self.player.add_card(self.deck.draw())
        self.dealer.add_card(self.deck.draw())
        self.player.add_card(self.deck.draw())
        self.dealer.add_card(self.deck.draw())

        # 檢查 BlackJack
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
            else:  # Stand
                break

        # 莊家回合（S17：17 停）
        self._show_table(header="莊家回合…")
        while self.dealer.value < 17:
            self.dealer.add_card(self.deck.draw())
            self._show_table(header="莊家要牌…")

        # 結算
        self._show_table(reveal_dealer=True, header="結算…")
        self._settle()

    # === 輔助：顯示/輸入 ===
    def _show_table(self, reveal_dealer: bool = False, header: str = "") -> None:
        clear_screen()
        if header:
            print(header)
            print("=" * 40)
        print(f"莊家: {render_hand(self.dealer.hand, hide_first=not reveal_dealer)}  (點數: {'?' if not reveal_dealer else self.dealer.value})")
        print(f"你  : {render_hand(self.player.hand)}  (點數: {self.player.value})")
        print("-" * 40)
        print(f"籌碼：{self.player.chips}    當前下注：{self.bet}")

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

    # === 結算規則 ===
    def _resolve_naturals(self) -> None:
        p_bj = self.player.has_blackjack()
        d_bj = self.dealer.has_blackjack()
        if p_bj and d_bj:
            print("雙方都是 Blackjack，平局（Push）。")
            # 返還下注
        elif p_bj:
            win = int(self.bet * 1.5)  # 3:2 淨贏（含退還本金為 2.5x）
            self.player.chips += win
            print(f"你是 Blackjack！贏得 {win}。")
        elif d_bj:
            self.player.chips -= self.bet
            print("莊家 Blackjack，你輸了。")
        input("按 Enter 繼續…")

    def _player_busts(self) -> None:
        self.player.chips -= self.bet
        print("你輸了。")
        input("按 Enter 繼續…")

    def _settle(self) -> None:
        p, d = self.player.value, self.dealer.value
        if d > 21:
            self.player.chips += self.bet
            print("莊家爆牌！你贏了。")
        elif p > d:
            self.player.chips += self.bet
            print("你贏了！")
        elif p < d:
            self.player.chips -= self.bet
            print("你輸了。")
        else:
            print("平局（Push）。")
        input("按 Enter 繼續…")


def main() -> None:
    clear_screen()
    print("歡迎來到 Blackjack（21 點）！")
    print("說明：Blackjack 3:2、莊家 17 停、A 可作 1 或 11。")
    name = input("請輸入你的名字（預設 Player）：").strip() or "Player"
    game = Game(player_name=name, num_decks=1)

    while True:
        if game.player.chips <= 0:
            print("你的籌碼用完了，遊戲結束！")
            break
        game.play_round()
        clear_screen()
        print(f"目前籌碼：{game.player.chips}")
        again = input("再來一局嗎？(Y/N)：").strip().upper()
        if again != "Y":
            break

    print("感謝遊玩！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已離開遊戲。")
        sys.exit(0)
