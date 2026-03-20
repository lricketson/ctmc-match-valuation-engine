import torch
from torch.distributions import Exponential


def simulate_step_gpu(current_states_idx, Q):
    """
    Simulates the next jump for an entire BATCH of matches simultaneously.
    current_states_idx: A 1D tensor of length N (e.g., 10,000) containing the current state indices.
    Q: The 240x240 transition matrix tensor.
    """
    batch_size = current_states_idx.shape[0]

    # 1. Extract the Q-matrix rows for all N universes simultaneously
    # rates shape: (10000, 240)
    rates = Q[current_states_idx].clone()

    # 2. Extract the diagonal elements (q_ii) for all universes
    # .gather pulls the specific value at the current state's index for each row
    q_ii = rates.gather(1, current_states_idx.unsqueeze(1)).squeeze(1)

    # 3. Create a safety mask (catch any absorbing states to prevent dividing by zero)
    valid_mask = torch.abs(q_ii) > 1e-8

    # Initialize our output tensors (defaulting to the 9999.0 freeze trap)
    dt = torch.full((batch_size,), 9999.0, device=Q.device)
    next_states_idx = current_states_idx.clone()

    # Only process the universes that aren't frozen
    if valid_mask.any():
        valid_q_ii = q_ii[valid_mask]
        exit_rates = -valid_q_ii

        # 4. Draw holding times for all valid universes at once
        # Math Note: PyTorch's Exponential takes the rate (lambda) directly,
        # unlike NumPy which wanted the scale (1/lambda).
        dist = Exponential(exit_rates)
        dt[valid_mask] = dist.sample()

        # 5. Calculate jump probabilities
        valid_rates = rates[valid_mask]

        # Zero out the diagonal so universes don't jump to the exact state they are already in
        # .scatter_ overwrites the specific index with 0.0
        current_valid_idx = current_states_idx[valid_mask].unsqueeze(1)
        valid_rates.scatter_(1, current_valid_idx, 0.0)

        # Divide by exit rate to get probabilities
        jump_probs = valid_rates / exit_rates.unsqueeze(1)
        jump_probs = torch.clamp(jump_probs, min=0.0)

        # Normalize to ensure floating point math sums to exactly 1.0
        prob_sums = jump_probs.sum(dim=1, keepdim=True)
        safe_prob_sums = torch.where(
            prob_sums > 0, prob_sums, torch.ones_like(prob_sums)
        )
        jump_probs = jump_probs / safe_prob_sums

        # 6. Roll 10,000 loaded dice simultaneously
        # torch.multinomial samples an index based on the row's probability weights
        valid_next_states = torch.multinomial(jump_probs, num_samples=1).squeeze(1)

        # Update the output tensor with the new states
        next_states_idx[valid_mask] = valid_next_states

    return next_states_idx, dt
