searchableChars = set("abcdefghijklmnopqrstuvwxyz 1234567890")
def makeSearchable(name):
    return "".join(filter(lambda c : c in searchableChars, name.strip().lower()))

def stringSearch(term, folder, limit=1):
    foundExact = list()
    foundPrefixed = list()
    foundContinuousPrefixedSequence = list()
    foundPrefixedSequence = list()
    foundContained = list()
    # foundSubset = list()

    noSpace = ' ' not in term
    
    termLen = len(term)
    
    for i in range(len(folder)):
        item = folder[i]
        spaceAccounting = item
        if(noSpace):
            spaceAccounting = item.replace(' ', '')

        if(spaceAccounting == term):
            foundExact.append(i)
            continue

        if(len(foundPrefixed) > limit):
            continue
        if(spaceAccounting.startswith(term)):
            foundPrefixed.append(i)
            continue

        if(len(foundContinuousPrefixedSequence) > limit):
            continue
        if(containsContinuousPrefixedSequence(item, term, 1)):
            foundContinuousPrefixedSequence.append(i)
            continue

        if(len(foundPrefixedSequence) > limit):
            continue
        if(containsPrefixedSequence(item, term)):
            foundPrefixedSequence.append(i)
            continue

        if(len(foundContained) > limit):
            continue
        if(term in spaceAccounting):
            foundContained.append(i)
            continue

        # if(len(foundSubset) > limit):
        #     continue
        # if(containsSequence(spaceAccounting, term)):
        #     foundSubset.append(item)
        #     continue

    return (
        foundExact + \
        foundPrefixed + \
        foundContinuousPrefixedSequence + \
        foundPrefixedSequence + \
        foundContained \
        )[:limit]

# def containsSequence(string, sequence):
#     print(string, sequence)
#     l = len(string)
#     if(len(sequence) > l):
#         return False

#     i = 0
#     for c in sequence:
#         found = False
#         while i < l:
#             if(c == string[i]):
#                 found = True
#                 i+=1
#                 break
#             else:
#                 i+=1
        
#         if(not found):
#             return False
#     return True

def containsContinuousPrefixedSequence(string, term, spaces=0):
    if(spaces > 1):
        return False

    if(len(term) > len(string)):
        return False

    if(len(term) == 0):
        return True

    if(term[0] == ' '):
        nextSpacePos = string.find(' ')
        return containsContinuousPrefixedSequence(string[nextSpacePos+1:], term[1:])
        
    thisAndRest = (term[0] == string[0] and containsContinuousPrefixedSequence(string[1:], term[1:]))
    if(thisAndRest):
        return True
    
    nextSpacePos = string.find(' ')
    if(nextSpacePos >= 0):
        return containsContinuousPrefixedSequence(string[nextSpacePos+1:], term, spaces+1)
    return False

def containsPrefixedSequence(string, term):
    if(len(term) > len(string)):
        return False

    if(len(term) == 0):
        return True

    if(term[0] == ' '):
        nextSpacePos = string.find(' ')
        return containsPrefixedSequence(string[nextSpacePos+1:], term[1:])

    thisAndRest = (term[0] == string[0] and containsPrefixedSequence(string[1:], term[1:]))
    if(thisAndRest):
        return True
    
    nextSpacePos = string.find(' ')
    if(nextSpacePos >= 0):
        return containsPrefixedSequence(string[nextSpacePos+1:], term)
    return False
