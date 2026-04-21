import numpy as np
import pandas as pd


def simulate_next_state(current_state, Q):
    """
    Takes the current state and the Q-matrix, and simulates the next jump.
    Returns the (next_state, time_spent_in_current_state).
    """
    # creates a dataframe of just the rates for that state
    rates = Q.loc[current_state].copy()

    # finds the negative sum of all the rates of transitioning to other states
    q_ii = rates[current_state]

    # --- SAFETY NET ---
    if pd.isna(q_ii) or abs(q_ii) <= 1e-8:
        return current_state, 9999.0

    # this is the total exit rate from the current state, indiscriminate of what new state it transitioned to
    exit_rate = -q_ii

    # draw the holding time from the exponential distribution. numpy uses scale instead of rate
    time_spent = np.random.exponential(scale=(1.0 / exit_rate))

    # We are now calculating the probabilities of jumping to other states.
    # set the rate of jumping from the state back to itself to be 0
    rates[current_state] = 0.0

    # find the probabilities of each state being jumped to by dividing each new state's individual transition rate
    # by the overall exit rate, to basically find what proportion of total jumps are to that state. this operation
    # is vectorised
    jump_probabilities = rates / exit_rate

    # just to make sure no proportions are negative
    jump_probabilities = jump_probabilities.clip(lower=0.0)

    prob_sum = jump_probabilities.sum()
    if pd.isna(prob_sum) or prob_sum == 0.0:
        return current_state, 9999.0

    # normalise
    jump_probabilities = jump_probabilities / prob_sum
    # 'index' is the name of each state, and this line takes each index in jump_probabilities and puts them into a list
    # index is like a key in a dictionary, and the probability is like the associated value
    possible_states = jump_probabilities.index.tolist()
    # np.random.choice works by associating the ith element of possible_states with the ith element of
    # jump_probabilities.values, and so each state has a prob attached to it, and the choice function picks one of those
    # by running a probability simulation
    next_state = np.random.choice(possible_states, p=jump_probabilities.values)

    return next_state, time_spent


def simulate_match(initial_state, Q, current_minute, current_second):
    """
    Simulates the remainder of a match from a given state and time.
    Returns the final outcome: 'Win', 'Draw', or 'Loss' (from the perspective of the target team).
    """
    # for v1.0, final whistle is hardcoded for 90 minutes. for v2.0, we'll calculate stoppage time dynamically
    end_of_match_seconds = 90 * 60
    current_time = (current_minute * 60) + current_second

    # start off with the initial state
    current_state = initial_state

    while current_time < end_of_match_seconds:
        next_state, dt = simulate_next_state(current_state, Q)

        # advance to the time of the next event
        current_time += dt
        # and move the ball to the next state
        current_state = next_state
        # if the simulation hit an empty row in the matrix, such as a state that a team never left (e.g.
        # due to game ending while in that state), terminate match early
        if dt > 9000:
            break
    # get the goal difference as a string
    final_g_str = current_state.split("_")[0].replace("G:", "")
    # then turn it to int
    final_delta_g = int(final_g_str)

    if final_delta_g > 0:
        return "Win"
    elif final_delta_g < 0:
        return "Loss"
    else:
        return "Draw"


def run_monte_carlo(
    initial_state, Q, current_minute, current_second, n_simulations=1000
):
    """
    Runs N independent Monte Carlo simulations of the match from the current state.
    Returns the implied probability distribution for a Win, Draw, and Loss.
    """
    # 1. Initialize a scorecard to track the outcomes of our N parallel universes
    results = {"Win": 0, "Draw": 0, "Loss": 0}

    # 2. Run the simulations
    for _ in range(n_simulations):
        outcome = simulate_match(initial_state, Q, current_minute, current_second)
        results[outcome] += 1

    # 3. Calculate the implied probabilities (The actual "Price" of the match)
    probabilities = {
        "Win_Prob": results["Win"] / n_simulations,
        "Draw_Prob": results["Draw"] / n_simulations,
        "Loss_Prob": results["Loss"] / n_simulations,
    }

    return probabilities


# --- The Grand V1.0 Test ---
# Let's say it's the 70th minute. Arsenal is tied 0-0. They just won the ball in Zone 14.
# initial_test_state = "G:0_P:1_Z:14"
# implied_odds = run_monte_carlo(initial_test_state, Q_matrix, 70, 0, n_simulations=1000)
# print(f"Live Match Pricing from {initial_test_state} at 70:00")
# print(f"Arsenal Win: {implied_odds['Win_Prob']:.1%}")
# print(f"Draw:        {implied_odds['Draw_Prob']:.1%}")
# print(f"Arsenal Loss:{implied_odds['Loss_Prob']:.1%}")


import pandas as pd
import numpy as np
from statsbombpy import sb


def process_match_generalised(match_id, home_team):
    """
    Pulls tick data for a single match, cleans it, and maps it to Home vs. Away CTMC states.
    Returns a DataFrame of valid S_i -> S_j transitions.
    """
    import warnings

    # turn off warnings for cleaner output
    warnings.filterwarnings("ignore")

    try:
        # 1. Fetch Event Data
        # get the data for every single event that occurred in the match: pass, tackle etc.
        events = sb.events(match_id=match_id)

        # 2. Clean Coordinates
        # break the [x, y] coordinates pair column into separate x and y columns
        events["x"] = events["location"].apply(
            lambda loc: loc[0] if isinstance(loc, list) else np.nan
        )
        events["y"] = events["location"].apply(
            lambda loc: loc[1] if isinstance(loc, list) else np.nan
        )

        # 3. Engineer Continuous Clock
        # add a column for how many seconds have passed in the period at the time of the event
        # (details about period in dataset_info.md)
        events["period_seconds"] = pd.to_timedelta(
            events["timestamp"]
        ).dt.total_seconds()
        # drop states that have no coordinates attached
        game_states = events.dropna(subset=["x", "y"]).copy()
        # this ensures exact chronological order
        game_states = game_states.sort_values(
            by=["period", "period_seconds"]
        ).reset_index(drop=True)

        # 4. Spatial Discretization (6x4 Grid)
        x_edges = np.linspace(0, 120, 7)
        y_edges = np.linspace(0, 80, 5)
        game_states["x_bin"] = pd.cut(
            game_states["x"], bins=x_edges, labels=False, include_lowest=True
        )
        game_states["y_bin"] = pd.cut(
            game_states["y"], bins=y_edges, labels=False, include_lowest=True
        )
        game_states["zone_id"] = (
            (game_states["x_bin"] * 4) + game_states["y_bin"]
        ).astype(int)

        # 5. Possession State
        game_states["P"] = (game_states["possession_team"] == home_team).astype(int)

        # 6. Construct State Vector
        game_states["state_id"] = (
            "P:"
            + game_states["P"].astype(str)
            + "_Z:"
            + game_states["zone_id"].astype(str)
        )

        # 7. Inject Absorbing States (Goals)
        is_goal = (game_states["type"] == "Shot") & (
            game_states["shot_outcome"] == "Goal"
        )

        is_out_of_play = (game_states["pass_outcome"] == "Out") | (
            (game_states["shot_outcome"].isin(["Off T", "Post", "Saved", "Wayward"]))
            | (game_states["type"] == "Clearance")
        )

        # Override state_id purely for these terminal events
        game_states.loc[is_goal & (game_states["team"] == home_team), "state_id"] = (
            "HOME_GOAL"
        )
        game_states.loc[is_goal & (game_states["team"] != home_team), "state_id"] = (
            "AWAY_GOAL"
        )
        game_states.loc[is_out_of_play, "state_id"] = "OUT_OF_PLAY"

        # 8. Calculate Transitions and Holding Times
        game_states["next_state_id"] = game_states.groupby("period")["state_id"].shift(
            -1
        )
        game_states["next_time"] = game_states.groupby("period")[
            "period_seconds"
        ].shift(-1)
        game_states["holding_time"] = (
            game_states["next_time"] - game_states["period_seconds"]
        )

        # 9. Enforce True Absorbing (Terminal) States
        # trap universes that go out of bounds
        terminal_states = ["HOME_GOAL", "AWAY_GOAL", "OUT_OF_PLAY"]
        game_states.loc[
            game_states["state_id"].isin(terminal_states), "next_state_id"
        ] = np.nan

        # 10. Return the clean transition ledger
        transitions = game_states.dropna(
            subset=["next_state_id", "holding_time"]
        ).copy()
        return transitions[
            [
                "match_id",
                "period",
                "period_seconds",
                "state_id",
                "next_state_id",
                "holding_time",
            ]
        ]

    except Exception as e:
        print(f"Skipping match {match_id} due to error: {e}")
        return pd.DataFrame()  # Return empty DF so the loop doesn't crash


def build_Q_matrix(transitions_df):
    # finds the number of times each exact state jump happened (e.g. how many times arsenal passed from the back to zone A4)
    transition_counts = (
        transitions_df.groupby(["state_id", "next_state_id"])
        .size()
        .reset_index(name="N_ij")
    )
    # finds the total time spent in each state
    state_holding_times = (
        transitions_df.groupby("state_id")["holding_time"].sum().reset_index(name="T_i")
    )
    # aligns N_ij and T_i for each state_id so we're dividing the relevant numbers by each other
    q_edges = pd.merge(transition_counts, state_holding_times, on="state_id")
    q_edges["q_ij"] = q_edges["N_ij"] / q_edges["T_i"]

    # takes the list of connections between states and their q_ij values and makes a 2x2 grid where the rows are the starting
    # states, the columns are destination states, and each intersection of these has its q_ij value of average rate of transition
    # I.e. if there were 100 states in total, then this would be a 100x100 grid
    # state transitions that never happened are filled with 0
    Q_matrix = q_edges.pivot(
        index="state_id", columns="next_state_id", values="q_ij"
    ).fillna(0.0)

    # creates a list of all states by taking every state that appears as either a row or column
    # a transition matrix needs to be square so we need to make sure every state appears, even if it doesn't have a matching
    # state that it transitions out of (bc it's at the end of the match or something)
    all_states = sorted(list(set(Q_matrix.index).union(set(Q_matrix.columns))))

    # fills values that don't have a matching state to transition to with 0
    Q_matrix = Q_matrix.reindex(index=all_states, columns=all_states, fill_value=0.0)

    # sets the diagonals to 0 so they don't interact with the sum at all
    np.fill_diagonal(Q_matrix.values, 0.0)
    # finds the sums of the next state transition rates for each state
    row_sums = Q_matrix.sum(axis=1)
    # fills the diagonal with a number such that the rows will sum to 0
    np.fill_diagonal(Q_matrix.values, -row_sums)

    return Q_matrix


def create_epl_transitions_ledger():
    import warnings

    # turn off warnings for cleaner output
    warnings.filterwarnings("ignore")
    # 1. Fetch the entire 2003/2004 Premier League Season
    all_season_matches = sb.matches(competition_id=2, season_id=44)

    # 2. Extract match IDs and their corresponding Home Teams
    match_data = list(
        zip(all_season_matches["match_id"], all_season_matches["home_team"])
    )
    print(f"Found {len(match_data)} total matches in the season.")

    all_transitions_league = []

    # 3. Process the entire league
    for idx, (m_id, h_team) in enumerate(match_data):
        if idx % 10 == 0:
            print(f"Processing Match {idx}/{len(match_data)}...")

        df_match = process_match_generalised(match_id=m_id, home_team=h_team)
        all_transitions_league.append(df_match)

    # 4. Concatenate into the Ultimate Master Ledger
    master_transitions = pd.concat(all_transitions_league, ignore_index=True)

    return master_transitions


def create_messi_data_transitions_ledger():
    import warnings

    # turn off warnings for cleaner output
    warnings.filterwarnings("ignore")

    free_comps = sb.competitions()

    la_liga_seasons = free_comps[free_comps["competition_id"] == 11][
        "season_id"
    ].tolist()
    print(f"Found {len(la_liga_seasons)} La Liga seasons to process.")

    match_data = []
    for s_id in la_liga_seasons:
        season_matches = sb.matches(competition_id=11, season_id=s_id)
        season_match_data = list(
            zip(season_matches["match_id"], season_matches["home_team"])
        )
        match_data.extend(season_match_data)
    print(f"Found {len(match_data)} total matches across all seasons.")

    all_transitions_league = []

    # 3. Process the entire league
    for idx, (m_id, h_team) in enumerate(match_data):
        if idx % 10 == 0:
            print(f"Processing Match {idx}/{len(match_data)}...")

        df_match = process_match_generalised(match_id=m_id, home_team=h_team)
        all_transitions_league.append(df_match)

    # 4. Concatenate into the Ultimate Master Ledger
    master_transitions = pd.concat(all_transitions_league, ignore_index=True)

    return master_transitions
