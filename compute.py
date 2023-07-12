from typing import Dict
import collections
import decimal
import classes

# Source: Starkscan, e.g.
# https://starkscan.co/token/0x049d36570d4e46f48e99674bd3fcc84644ddd6b96f7c741b1562b82f9e004dc7 for ETH.
TOKEN_DECIMAL_FACTORS = {
    "ETH": decimal.Decimal("1e18"),
    "wBTC": decimal.Decimal("1e8"),
    "USDC": decimal.Decimal("1e6"),
    "DAI": decimal.Decimal("1e18"),
    "USDT": decimal.Decimal("1e6"),
}


# Source: https://zklend.gitbook.io/documentation/using-zklend/technical/asset-parameters.
COLLATERAL_FACTORS = {
    "ETH": decimal.Decimal("0.80"),
    "wBTC": decimal.Decimal("0.70"),
    "USDC": decimal.Decimal("0.80"),
    "DAI": decimal.Decimal("0.70"),
    "USDT": decimal.Decimal("0.70"),
}


# Source: https://zklend.gitbook.io/documentation/using-zklend/technical/asset-parameters.
LIQUIDATION_BONUSES = {
    "ETH": decimal.Decimal("0.10"),
    "wBTC": decimal.Decimal("0.15"),
    "USDC": decimal.Decimal("0.10"),
    "DAI": decimal.Decimal("0.10"),
    "USDT": decimal.Decimal("0.10"),
}


def compute_risk_adjusted_collateral_usd(
    user_state: classes.UserState,
    prices: Dict[str, decimal.Decimal],
) -> decimal.Decimal:
    return sum(
        token_state.collateral_enabled
        * token_state.deposit
        * COLLATERAL_FACTORS[token]
        * prices[token]
        # TODO: perform the conversion using TOKEN_DECIMAL_FACTORS sooner (in `UserTokenState`?)?
        / TOKEN_DECIMAL_FACTORS[token]
        for token, token_state in user_state.token_states.items()
    )


def compute_borrowings_usd(
    user_state: classes.UserState,
    prices: Dict[str, decimal.Decimal],
) -> decimal.Decimal:
    return sum(
        token_state.borrowings * prices[token]
        # TODO: perform the conversion using TOKEN_DECIMAL_FACTORS sooner (in `UserTokenState`?)?
        / TOKEN_DECIMAL_FACTORS[token]
        for token, token_state in user_state.token_states.items()
    )


def compute_health_factor(
    risk_adjusted_collateral_usd: decimal.Decimal,
    borrowings_usd: decimal.Decimal,
) -> decimal.Decimal:
    if borrowings_usd == decimal.Decimal("0"):
        # TODO: assumes collateral is positive
        return decimal.Decimal("Inf")

    health_factor = risk_adjusted_collateral_usd / borrowings_usd
    # TODO: enable?
    #     if health_factor < decimal.Decimal('0.9'):
    #         print(f'Suspiciously low health factor = {health_factor} of user = {user}, investigate.')
    # TODO: too many loans eligible for liquidation?
    #     elif health_factor < decimal.Decimal('1'):
    #         print(f'Health factor = {health_factor} of user = {user} eligible for liquidation.')
    return health_factor


# TODO: compute_health_factor, etc. should be methods of class UserState
def compute_borrowings_to_be_liquidated(
    risk_adjusted_collateral_usd: decimal.Decimal,
    borrowings_usd: decimal.Decimal,
    borrowings_token_price: decimal.Decimal,
    collateral_token_collateral_factor: decimal.Decimal,
    collateral_token_liquidation_bonus: decimal.Decimal,
) -> decimal.Decimal:
    # TODO: commit the derivation of the formula in a document?
    numerator = borrowings_usd - risk_adjusted_collateral_usd
    denominator = borrowings_token_price * (
        1
        - collateral_token_collateral_factor * (1 + collateral_token_liquidation_bonus)
    )
    return numerator / denominator


def compute_max_liquidated_amount(
    state: classes.State,
    prices: Dict[str, decimal.Decimal],
    borrowings_token: str,
) -> decimal.Decimal:
    liquidated_borrowings_amount = decimal.Decimal("0")
    for user, user_state in state.user_states.items():
        # TODO: do this?
        # Filter out users who borrowed the token of interest.
        borrowings_tokens = {
            token_state.token
            for token_state in user_state.token_states.values()
            if token_state.borrowings > decimal.Decimal("0")
        }
        if not borrowings_token in borrowings_tokens:
            continue

        # Filter out users with health below 1.
        risk_adjusted_collateral_usd = compute_risk_adjusted_collateral_usd(
            user_state=user_state,
            prices=prices,
        )
        borrowings_usd = compute_borrowings_usd(
            user_state=user_state,
            prices=prices,
        )
        health_factor = compute_health_factor(
            risk_adjusted_collateral_usd=risk_adjusted_collateral_usd,
            borrowings_usd=borrowings_usd,
        )
        if health_factor >= decimal.Decimal("1"):
            continue

        # TODO: find out how much of the borrowings_token will be liquidated
        collateral_tokens = {
            token_state.token
            for token_state in user_state.token_states.values()
            if token_state.deposit * token_state.collateral_enabled
            > decimal.Decimal("0")
        }
        # TODO: choose the most optimal collateral_token to be liquidated .. or is the liquidator indifferent?
        collateral_token = list(collateral_tokens)[0]
        liquidated_borrowings_amount += compute_borrowings_to_be_liquidated(
            risk_adjusted_collateral_usd=risk_adjusted_collateral_usd,
            borrowings_usd=borrowings_usd,
            borrowings_token_price=prices[borrowings_token],
            collateral_token_collateral_factor=COLLATERAL_FACTORS[collateral_token],
            collateral_token_liquidation_bonus=LIQUIDATION_BONUSES[collateral_token],
        )
    return liquidated_borrowings_amount


def decimal_range(start: decimal.Decimal, stop: decimal.Decimal, step: decimal.Decimal):
    while start < stop:
        yield start
        start += step