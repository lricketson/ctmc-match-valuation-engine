it outputted 51x51 so exactly right. so what we've done so far is this right?:

refactored the match processing function to not include goal diff, so a player's xT at 0-0 is considered the same as if it was 3-0. which makes sense. this also makes the q matrix less sparse so theres more data for each state, giving a fuller picture

created markers of a play ending (in either a goal or ball going out of play) to indicate that the play did/didn't end in a goal, which is used to calculate expected threat of a player. (not 100% sure if taht sentence is accurate.)
