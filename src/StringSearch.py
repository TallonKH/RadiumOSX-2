searchableChars = set("abcdefghijklmnopqrstuvwxyz _-&1234567890")
def makeSearchable(name):
    return "".join(filter(lambda c : c in searchableChars, name.strip().lower()))

def stringSearch(term, folder, limit=1):
    foundExact = list()
    foundFirstWord = list()
    foundWord = list()
    foundPrefixed = list()
    foundContinuousPrefixedSequence = list()
    foundPrefixedSequence = list()
    foundContained = list()

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

        if(noSpace):
            words = item.split(" ")
            if(len(words) > 1):
                first = words[0]
                rest = words[1:]
                if(len(foundFirstWord) > limit):
                    continue
                if(first == term):
                    foundFirstWord.append(i)
                    continue

                if(len(foundWord) > limit):
                    continue
                if(term in rest):
                    foundWord.append(i)
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

    return (
        foundExact + \
        foundFirstWord + \
        foundWord + \
        foundPrefixed + \
        foundContinuousPrefixedSequence + \
        foundPrefixedSequence + \
        foundContained \
        )[:limit]

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
